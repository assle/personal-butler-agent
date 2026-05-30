"""
数据库声明式基类
所有 ORM 模型继承自此基类，由 SQLAlchemy 管理表结构映射

在总流程中的位置:
  models/ 中的 ORM 类继承 Base → Base.metadata 注册所有表
  lifespan 启动时 Base.metadata.create_all 创建表结构
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类，所有 ORM 模型的父类

    子类通过 __tablename__ 定义表名，Mapped 列自动注册到 metadata
    """
    pass
