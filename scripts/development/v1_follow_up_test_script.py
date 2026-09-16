"""生成 V1 一次性事项跟进真机验收台词，不访问服务或个人数据库。

自然语言跟进只接受明确日期和分钟。手工心算容易把时间设成已经过去，或使用
“过一会儿”这类故意不支持的模糊表达。本工具只根据本机当前时间打印两句可直接
念给圆屏的话：先创建一个虚拟事项，再把它改到更晚的分钟。
"""

from __future__ import annotations

from datetime import datetime, timedelta


def _spoken_time(value: datetime) -> str:
    hour = value.hour
    if hour == 0:
        return f"凌晨十二点{value.minute:02d}分"
    if hour < 12:
        return f"上午{hour}点{value.minute:02d}分"
    if hour == 12:
        return f"中午十二点{value.minute:02d}分"
    if hour < 18:
        return f"下午{hour - 12}点{value.minute:02d}分"
    return f"晚上{hour - 12}点{value.minute:02d}分"


def acceptance_lines(now: datetime) -> tuple[datetime, datetime, str, str]:
    """把首个时刻留足六分钟，改时后再留五分钟观察旧时刻。"""

    next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    original = next_minute + timedelta(minutes=6)
    changed = original + timedelta(minutes=5)
    if changed.date() != now.date():
        # 正式解析器故意拒绝容易混淆的“十二点”和无时段 0～12 点。
        # 临近午夜时跨日等待也不适合十几分钟验收，直接说明边界，不生成假台词。
        raise ValueError("当前距离午夜太近，请在零点后重新运行本脚本。")
    date_word = "今天" if original.date() == now.date() else "明天"
    create = (
        f"我{date_word}{_spoken_time(original)}要检查虚拟项目发布记录，"
        "到时候问我检查结果。"
    )
    change = f"请把时间改成{_spoken_time(changed)}。"
    return original, changed, create, change


def main() -> None:
    try:
        original, changed, create, change = acceptance_lines(datetime.now().astimezone())
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print("V1 一次性跟进真机验收台词")
    print(f"旧时刻：{original:%Y-%m-%d %H:%M}")
    print(f"新时刻：{changed:%Y-%m-%d %H:%M}")
    print(f"第一句：{create}")
    print(f"第二句：{change}")
    print("请在旧时刻确认没有播报，并在新时刻确认圆屏实际播报。")


if __name__ == "__main__":
    main()
