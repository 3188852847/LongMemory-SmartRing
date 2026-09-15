"""CosyVoice 的自然文本边界与单任务调度，不接触 Memory Core 或设备协议。"""

import threading


_BOUNDARIES = frozenset("，,、。？?！!；;：:")


class _SegmentState:
    def __init__(self, tts):
        self.connection = getattr(tts, "conn", None)
        # 合成、最终清空可能经过相同的包装入口；只让最外层负责调度，避免递归。
        self.local = threading.local()

    def current(self, tts, sentence_id):
        if getattr(tts, "tts_stop_request", False):
            return False
        if sentence_id is not None and getattr(tts, "current_sentence_id", None) != sentence_id:
            return False
        connection = self.connection
        if connection is None:
            return True
        stop_event = getattr(connection, "stop_event", None)
        return not (
            getattr(connection, "client_abort", False)
            or (stop_event is not None and stop_event.is_set())
            or (sentence_id is not None and getattr(connection, "sentence_id", sentence_id) != sentence_id)
        )


def install_cosyvoice_punctuation_policy(tts, *, minimum_chars=18, first_minimum_chars=16):
    """合并短开头；首段和后续段都只在顺序遇到的首个合格自然标点结束。"""
    if (type(minimum_chars) is not int or minimum_chars < 8
            or type(first_minimum_chars) is not int or first_minimum_chars < 8):
        raise ValueError("punctuation_segment_limit_invalid")
    if getattr(tts, "_longmemory_punctuation_policy", None) == "cosyvoice3":
        return
    if not callable(getattr(tts, "_get_segment_text", None)):
        return
    state = _SegmentState(tts)

    def get_segment_text():
        sentence_id = getattr(tts, "current_sentence_id", None)
        if not state.current(tts, sentence_id):
            return None
        full_text = "".join(getattr(tts, "tts_text_buff", ()))
        processed = getattr(tts, "processed_chars", 0)
        current = full_text[processed:]
        minimum = minimum_chars
        if getattr(tts, "is_first_sentence", False):
            first_boundary = next(
                (index + 1 for index, char in enumerate(current) if char in _BOUNDARIES), None
            )
            if first_boundary is None:
                return None
            # 8/16 来自本轮固定句对照的启发式，不保证任意文本无欠载。只延长很短
            # 的开头；本来已足够长的首分句保持首声。每次从文本纯计算，不跨轮记状态。
            minimum = first_minimum_chars if first_boundary < 8 else 8
        # 不沿用上游 rfind：同一份文本不能因 LLM 增量大小不同而改在最后一个逗号切。
        # 阈值只决定哪些标点可结束片段，永远不直接在第 N 个字截断。
        for index, char in enumerate(current):
            if index + 1 >= minimum and char in _BOUNDARIES:
                raw = current[:index + 1]
                tts.processed_chars = processed + len(raw)
                tts.is_first_sentence = False
                return raw.strip()
        return None

    tts._get_segment_text = get_segment_text
    if callable(getattr(tts, "_process_remaining_text_stream", None)):
        def flush_remaining(opus_handler=None):
            sentence_id = getattr(tts, "current_sentence_id", None)
            if getattr(state.local, "flushing", False) or not state.current(tts, sentence_id):
                return False
            state.local.flushing = True
            emitted = False
            try:
                while state.current(tts, sentence_id):
                    before = tts.processed_chars
                    segment = get_segment_text()
                    if tts.processed_chars <= before:
                        break
                    if segment:
                        tts.to_tts_stream(segment, opus_handler=opus_handler)
                        emitted = True
                        if not state.current(tts, sentence_id):
                            return emitted
                if not state.current(tts, sentence_id):
                    return emitted
                full_text = "".join(getattr(tts, "tts_text_buff", ()))
                tail = full_text[tts.processed_chars:].strip()
                if tail:
                    # 不足阈值的完整短回复在 LAST/FILE 一次送出，保留标点才能维持
                    # 自然语气并命中完整预置语音。flushing 阻止外层在偏移提交前重播。
                    tts.to_tts_stream(tail, opus_handler=opus_handler)
                    emitted = True
                    if not state.current(tts, sentence_id):
                        return emitted
                    tts.is_first_sentence = False
                # FILE 后还会有 TEXT；使用真实末尾，不能再累加全缓冲长度。
                tts.processed_chars = len(full_text)
                return emitted
            finally:
                state.local.flushing = False

        tts._process_remaining_text_stream = flush_remaining
    tts._longmemory_cosy_segment_state = state
    tts._longmemory_punctuation_minimum_chars = minimum_chars
    tts._longmemory_punctuation_first_minimum_chars = first_minimum_chars
    tts._longmemory_punctuation_policy = "cosyvoice3"


def install_cosyvoice_ready_segment_drain(tts, connection):
    """放在单段 V6 计时包装外侧：合成返回后立即处理缓冲中已经闭合的下一段。"""
    if getattr(tts, "_longmemory_ready_segments_installed", False):
        return
    state = getattr(tts, "_longmemory_cosy_segment_state", None)
    measured_stream = getattr(tts, "to_tts_stream", None)
    if state is None or not callable(measured_stream):
        return
    state.connection = connection

    def stream(text, *args, **kwargs):
        sentence_id = getattr(tts, "current_sentence_id", None)
        if not state.current(tts, sentence_id):
            return None
        if getattr(state.local, "draining", False) or getattr(state.local, "flushing", False):
            return measured_stream(text, *args, **kwargs)
        state.local.draining = True
        try:
            result = measured_stream(text, *args, **kwargs)
            while state.current(tts, sentence_id):
                before = tts.processed_chars
                segment = tts._get_segment_text()
                if tts.processed_chars <= before:
                    break
                if segment and state.current(tts, sentence_id):
                    # 捕获的内层每次单独计时；不能再次调用 tts.to_tts_stream 递归调度。
                    measured_stream(segment, *args, **kwargs)
            return result
        finally:
            state.local.draining = False

    tts.to_tts_stream = stream
    tts._longmemory_ready_segments_installed = True
