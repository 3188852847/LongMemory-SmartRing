"""工程骨架的最小冒烟测试。"""


def test_longmemory_package_is_importable() -> None:
    """确认 pytest 能按 src layout 导入项目主包。"""
    import longmemory

    assert longmemory.__version__ == "0.1.0"
