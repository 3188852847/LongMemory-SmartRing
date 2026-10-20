"""答案协议边界：独立推理字段不作正文，仅识别开头的显式think控制块。"""


OPEN, CLOSE = '<think>', '</think>'


class FinalContent:
    """逐增量处理；只保留标签前缀/结束标签尾部，不缓存整段推理或答案。"""

    def __init__(self):
        self.mode = 'prefix'
        self.pending = ''
        self.depth = 0

    def feed(self, text):
        if not isinstance(text, str):
            raise ValueError('answer_content_invalid')
        if self.mode == 'final':
            return text
        self.pending += text
        while True:
            if self.mode == 'prefix':
                start = self.pending.lstrip()
                if len(self.pending) - len(start) > 64:
                    raise ValueError('answer_prefix_too_large')
                if not start or (OPEN.startswith(start) and start != OPEN):
                    return ''
                if not start.startswith(OPEN):
                    self.mode = 'final'
                    result, self.pending = self.pending, ''
                    return result
                self.pending = start[len(OPEN):]
                self.mode, self.depth = 'reasoning', 1
            # 在显式块中丢弃正文，只留可能跨增量的控制标签尾部。
            opening, closing = self.pending.find(OPEN), self.pending.find(CLOSE)
            positions = [(index, tag) for index, tag in ((opening, OPEN), (closing, CLOSE)) if index >= 0]
            if not positions:
                self.pending = self.pending[-(len(CLOSE) - 1):]
                return ''
            index, tag = min(positions)
            self.pending = self.pending[index + len(tag):]
            self.depth += 1 if tag == OPEN else -1
            if self.depth > 32:
                raise ValueError('answer_reasoning_nesting_invalid')
            if not self.depth:
                self.mode = 'prefix'

    def finish(self):
        if self.mode == 'reasoning' or self.pending.strip():
            raise ValueError('answer_reasoning_incomplete')
        result, self.pending = self.pending, ''
        return result


def final_message(message):
    """仅处理assistant消息字段；工具参数、普通正文和未知元数据不改写。"""
    if not isinstance(message, dict):
        raise ValueError('answer_message_invalid')
    result = dict(message)
    result.pop('reasoning_content', None)
    content = result.get('content')
    if isinstance(content, str):
        parser = FinalContent()
        result['content'] = parser.feed(content) + parser.finish()
    return result


def final_response(packet):
    result = dict(packet)
    choices = []
    for choice in packet.get('choices') or []:
        choice = dict(choice)
        if 'message' in choice:
            choice['message'] = final_message(choice['message'])
        choices.append(choice)
    if 'choices' in packet:
        result['choices'] = choices
    return result


class FinalStream:
    def __init__(self):
        self.choices = {}

    def packet(self, packet):
        result, choices = dict(packet), []
        for position, original in enumerate(packet.get('choices') or []):
            choice = dict(original)
            index = choice.get('index', position)
            if type(index) is not int or not 0 <= index < 32:
                raise ValueError('answer_choice_invalid')
            parser = self.choices.setdefault(index, FinalContent())
            if choice.get('delta') is not None:
                delta = dict(choice['delta'])
                delta.pop('reasoning_content', None)
                if delta.get('content') is not None:
                    delta['content'] = parser.feed(delta['content'])
                choice['delta'] = delta
            if choice.get('finish_reason') is not None:
                parser.finish()
            choices.append(choice)
        if 'choices' in packet:
            result['choices'] = choices
        return result

    def finish(self):
        for parser in self.choices.values():
            parser.finish()
