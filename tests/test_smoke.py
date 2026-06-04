"""
应用入口烟雾测试
验证 FastAPI 应用可以导入，并且旧本地 debug 消息入口已移除。
"""


def test_app_imports():
    """验证 FastAPI app 可以导入"""
    from src.main import app

    assert app.title == "Personal Butler Agent"


def test_debug_route_removed():
    """验证本地 debug 消息入口已删除"""
    from src.main import app

    paths = {route.path for route in app.routes}
    assert "/api/debug/message" not in paths
