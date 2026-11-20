def invoke_hy_management(runtime, operation, **arguments):
    """只走 Runtime 的受限扩展；未接线时绝不直接调用 SDK 绕过运行守卫。"""
    from longmemory.methods.contracts import UnsupportedCapabilityError
    extension = getattr(runtime, "administer_extension", None)
    if extension is None:
        raise UnsupportedCapabilityError("hy_management_runtime_extension_unavailable")
    return extension("hy_memory", operation, **arguments)
