"""工程骨架和安装状态的最小冒烟测试。"""

from importlib.metadata import version


def test_longmemory_package_is_importable() -> None:
    """确认当前 Python 环境能够导入项目主包。"""

    import longmemory

    assert longmemory.__version__ == "0.1.0"


def test_project_distribution_is_installed() -> None:
    """确认项目已作为发行包安装，而非只依赖 pytest 的 src 路径。"""

    assert version("longmemory-smartring") == "0.1.0"