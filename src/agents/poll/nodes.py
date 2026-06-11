"""
PollAgent 节点函数
实现投票意图分类、创建投票、投票、查看结果和结束投票五个节点。

Workflow:
  classify_poll_intent 根据关键词或状态中的 category 分流
  → create_poll_node / cast_vote_node / view_results_node / end_poll_node
  → 返回 reply 和 data
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from langgraph.config import get_config
from sqlalchemy import func, select

from src.models.poll import Poll, PollVote
from src.models.group_webhook import GroupWebhook

# ── 常量 ──────────────────────────────────────────────

TIME_PARSE_PROMPT = """你是时间解析器。从用户消息中提取投票结束时间，只返回 ISO 8601 格式的 UTC 时间字符串，例如"2026-06-12T09:00:00Z"。

当前时间：{now}
默认时区：Asia/Shanghai

规则：
- "明天下午5点" → 明天的 17:00 CST → 明天的 09:00 UTC
- "一小时后" → 当前时间 + 1 小时
- "周五12点" → 本周五 12:00 CST
- 如果没有指定结束时间，返回空字符串""

只返回时间字符串或空字符串，不要输出其他内容。"""


# ── 选项解析 ───────────────────────────────────────────

def _parse_poll_options(message: str) -> list[str] | None:
    """从消息中解析投票选项

    参数:
        message: 用户原始消息

    返回:
        list[str] | None: 选项列表；解析失败返回 None
    """
    pattern = r"([A-Za-z])[.、．]\s*([^\s,，A-Za-z0-9]+(?:[^\s,，]*[^\s,，])?)"
    matches: list[tuple[str, str]] = re.findall(pattern, message)
    if len(matches) < 2:
        return None
    seen_letters: set[str] = set()
    options: list[str] = []
    for letter, label in matches:
        lower = letter.lower()
        if lower in seen_letters:
            continue
        seen_letters.add(lower)
        options.append(label.strip())
    if len(options) < 2:
        return None
    return options


def _extract_title(message: str) -> str:
    """从消息中提取投票标题

    参数:
        message: 用户原始消息

    返回:
        str: 投票标题
    """
    title = re.sub(r"[A-Za-z][.、．]\s*[^\s,，]+", "", message)
    title = re.sub(r"，?\s*(明天|今天|后天|周[一二三四五六日]|\d+点|\d+:\d+|一?小?时后|结束|截止).*$", "", title)
    for keyword in ("创建投票", "发起投票", "新建投票", "投票", "："):
        title = title.replace(keyword, "", 1)
    return title.strip().strip("：:").strip() or "投票"


# ── 投票选项字母识别 ────────────────────────────────────

def _parse_vote_option(message: str, option_count: int) -> int | None:
    """从短消息中提取投票选项序号

    参数:
        message: 用户消息
        option_count: 当前投票的选项总数

    返回:
        int | None: 选项序号（0-based）；无法识别返回 None
    """
    text = message.strip()
    m = re.match(r"投票\s*([A-Za-z])", text)
    if m:
        letter = m.group(1)
    else:
        m = re.match(r"选\s*([A-Za-z])", text)
        if m:
            letter = m.group(1)
        else:
            m = re.match(r"([A-Za-z])$", text)
            if m:
                letter = m.group(1)
            else:
                return None
    index = ord(letter.lower()) - ord("a")
    if 0 <= index < option_count:
        return index
    return None


# ── 时间解析 ───────────────────────────────────────────

async def _parse_end_time(message: str, llm) -> datetime | None:
    """调用 LLM 解析自然语言结束时间

    参数:
        message: 用户原始消息
        llm: LLMClient 实例

    返回:
        datetime | None: UTC 结束时间；解析失败返回 None
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = await llm.chat(
        messages=[
            {"role": "system", "content": TIME_PARSE_PROMPT.format(now=now)},
            {"role": "user", "content": message},
        ],
        temperature=0.1,
    )
    text = raw.strip().strip('"').strip("'")
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


# ── 格式化 ─────────────────────────────────────────────

def _format_poll_card(poll: Poll) -> str:
    """格式化投票卡片

    参数:
        poll: Poll ORM 对象

    返回:
        str: 投票展示文本
    """
    options = poll.options
    if isinstance(options, str):
        options = json.loads(options)
    labels = [f"{chr(65 + i)}. {opt}" for i, opt in enumerate(options)]
    lines = [f"投票已创建「{poll.title}」", " | ".join(labels)]
    if poll.end_time:
        end_str = poll.end_time.strftime("%Y-%m-%d %H:%M")
        lines.append(f"截止：{end_str}（UTC）")
    lines.append("回复 @bot + 选项字母即可投票")
    return "\n".join(lines)


def _format_results(poll: Poll, counts: dict[int, int]) -> str:
    """格式化投票结果

    参数:
        poll: Poll ORM 对象
        counts: {option_index: vote_count}

    返回:
        str: 结果展示文本
    """
    options = poll.options
    if isinstance(options, str):
        options = json.loads(options)
    total = sum(counts.values())
    max_votes = max(counts.values()) if counts else 0
    lines = []
    for i, opt in enumerate(options):
        cnt = counts.get(i, 0)
        marker = " （获胜）" if cnt == max_votes and cnt > 0 else ""
        lines.append(f"{chr(65 + i)}.{opt} {cnt}票{marker}")
    status = "结束" if poll.status == "ended" else "当前"
    header = f"{status}投票「{poll.title}」"
    return header + "\n" + " | ".join(lines) + f"\n共{total}人参与"


# ── 节点函数 ───────────────────────────────────────────

async def _get_active_poll(db, chat_id: str) -> Poll | None:
    """查询群内最近一个活跃投票

    参数:
        db: SQLAlchemy 异步会话
        chat_id: 群聊 ID

    返回:
        Poll | None: 最近创建的 active poll；无则 None
    """
    result = await db.execute(
        select(Poll)
        .where(Poll.chat_id == chat_id, Poll.status == "active")
        .order_by(Poll.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_active_polls(db, chat_id: str) -> list[Poll]:
    """查询群内所有活跃投票

    参数:
        db: SQLAlchemy 异步会话
        chat_id: 群聊 ID

    返回:
        list[Poll]: 活跃投票列表，按创建时间降序
    """
    result = await db.execute(
        select(Poll)
        .where(Poll.chat_id == chat_id, Poll.status == "active")
        .order_by(Poll.created_at.desc())
    )
    return list(result.scalars().all())


async def _count_votes(db, poll_id: int) -> dict[int, int]:
    """统计投票选项的票数

    参数:
        db: SQLAlchemy 异步会话
        poll_id: 投票 ID

    返回:
        dict[int, int]: {option_index: vote_count}
    """
    result = await db.execute(
        select(PollVote.option_index, func.count(PollVote.id))
        .where(PollVote.poll_id == poll_id)
        .group_by(PollVote.option_index)
    )
    return {row[0]: row[1] for row in result.all()}


async def classify_poll_intent(state: dict) -> dict:
    """分类投票意图

    参数:
        state: PollState

    返回:
        dict: 包含 intent 的状态更新
    """
    existing = state.get("intent", "")
    if existing in {"create_poll", "cast_vote", "view_results", "end_poll"}:
        return {"intent": existing}
    return {"intent": "view_results", "reply": "无法识别投票操作，请说明要创建投票、投票、查看结果还是结束投票。"}


async def create_poll_node(state: dict) -> dict:
    """创建群投票：解析选项和时间，写入 Poll 表，注册调度任务

    参数:
        state: PollState

    返回:
        dict: 包含 reply 的状态更新
    """
    config = get_config()["configurable"]
    db = config["db"]
    llm = config["llm"]
    scheduler_manager = config.get("scheduler_manager")
    message = state.get("message", "")
    user_id = state.get("user_id", "")
    chat_id = state.get("chat_id", "")

    options = _parse_poll_options(message)
    if options is None:
        return {"reply": "请使用格式创建投票：\n创建投票：标题？A.选项1 B.选项2 C.选项3\n\n至少需要2个选项。"}

    title = _extract_title(message)
    end_time = await _parse_end_time(message, llm)

    poll = Poll(
        chat_id=chat_id,
        creator_user_id=user_id,
        title=title,
        options=options,
        end_time=end_time,
        status="active",
    )
    db.add(poll)
    await db.flush()

    if end_time and scheduler_manager is not None:
        try:
            scheduler_manager.schedule_poll_end(poll.id, end_time)
        except Exception:
            pass

    return {"reply": _format_poll_card(poll), "data": {"poll_id": poll.id}}


async def cast_vote_node(state: dict) -> dict:
    """记录或更新投票

    参数:
        state: PollState

    返回:
        dict: 包含 reply 的状态更新
    """
    config = get_config()["configurable"]
    db = config["db"]
    message = state.get("message", "")
    user_id = state.get("user_id", "")
    chat_id = state.get("chat_id", "")

    active_polls = await _get_active_polls(db, chat_id)
    if not active_polls:
        return {"reply": "当前没有进行中的投票。"}

    poll = active_polls[0]

    if len(active_polls) > 1:
        sub = re.search(r"投票\s*(\d+)", message)
        if sub:
            idx = int(sub.group(1)) - 1
            if 0 <= idx < len(active_polls):
                poll = active_polls[idx]
            else:
                return {"reply": f"投票编号 {idx + 1} 不存在，当前有 {len(active_polls)} 个进行中的投票。"}
        else:
            m2 = re.search(r"给\s*([^\s]+)", message)
            if m2:
                keyword = m2.group(1)
                matched = [p for p in active_polls if keyword in p.title]
                if len(matched) == 1:
                    poll = matched[0]
                elif len(matched) > 1:
                    titles = "、".join(p.title for p in matched)
                    return {"reply": f"「{keyword}」匹配到多个投票：{titles}\n请用「@bot 投票1 A」指明。"}
                else:
                    titles = "、".join(p.title for p in active_polls)
                    return {"reply": f"当前有 {len(active_polls)} 个进行中的投票：{titles}\n请用「@bot 投票1 A」或「@bot 给「标题」投A」指明。"}
            else:
                titles = " | ".join(f"投票{i+1}「{p.title}」" for i, p in enumerate(active_polls))
                return {"reply": f"当前有 {len(active_polls)} 个进行中的投票：{titles}\n回复「@bot 投票1 A」或直接「@bot A」投给最近创建的投票。"}

    option_index = _parse_vote_option(message, len(poll.options))
    if option_index is None:
        return {
            "reply": f"无法识别你的投票选项。请回复「@bot A」或「@bot 选B」（可选：{', '.join(chr(65 + i) for i in range(len(poll.options)))}）"
        }

    existing_vote = await db.execute(
        select(PollVote).where(
            PollVote.poll_id == poll.id,
            PollVote.user_id == user_id,
        )
    )
    vote = existing_vote.scalar_one_or_none()

    if vote is not None:
        old_label = poll.options[vote.option_index]
        vote.option_index = option_index
        vote.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        new_label = poll.options[option_index]
        return {
            "reply": f"已改票：从「{old_label}」→「{new_label}」",
            "data": {"poll_id": poll.id, "option_index": option_index},
        }

    db.add(PollVote(
        poll_id=poll.id,
        user_id=user_id,
        option_index=option_index,
    ))
    label = poll.options[option_index]
    return {
        "reply": f"已记录：你投了「{label}」",
        "data": {"poll_id": poll.id, "option_index": option_index},
    }


async def view_results_node(state: dict) -> dict:
    """查看当前投票结果

    参数:
        state: PollState

    返回:
        dict: 包含 reply 的状态更新
    """
    config = get_config()["configurable"]
    db = config["db"]
    chat_id = state.get("chat_id", "")

    poll = await _get_active_poll(db, chat_id)
    if poll is None:
        return {"reply": "当前没有进行中的投票。"}

    counts = await _count_votes(db, poll.id)
    return {"reply": _format_results(poll, counts), "data": {"poll_id": poll.id, "counts": counts}}


async def end_poll_node(state: dict) -> dict:
    """结束投票：标记 ended，取消调度任务，推送结果

    参数:
        state: PollState

    返回:
        dict: 包含 reply 的状态更新
    """
    config = get_config()["configurable"]
    db = config["db"]
    chat_id = state.get("chat_id", "")
    scheduler_manager = config.get("scheduler_manager")
    webhook_client = config.get("webhook_client")

    poll = await _get_active_poll(db, chat_id)
    if poll is None:
        return {"reply": "当前没有进行中的投票。"}

    poll.status = "ended"
    await db.flush()

    if scheduler_manager is not None:
        scheduler_manager.cancel_poll_end(poll.id)

    counts = await _count_votes(db, poll.id)
    result_text = _format_results(poll, counts)

    webhook_pushed = False
    if webhook_client is not None:
        webhook = await db.execute(
            select(GroupWebhook).where(GroupWebhook.chat_id == chat_id)
        )
        wh = webhook.scalar_one_or_none()
        if wh is not None:
            await webhook_client.send_markdown(wh.webhook_url, result_text)
            webhook_pushed = True

    suffix = "" if webhook_pushed else "\n（未配置群 webhook，无法主动推送）"
    return {"reply": result_text + suffix, "data": {"poll_id": poll.id, "counts": counts}}
