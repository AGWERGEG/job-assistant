"""Short-lived API transport child. Secrets arrive on stdin, never command arguments."""
import json
import sys
from .providers import _complete_blocking
from .store import Problem


def emit(kind, text):
    print(json.dumps({'type':kind,'text':text}, ensure_ascii=False), flush=True)


def main():
    try:
        value = json.load(sys.stdin)
        result = _complete_blocking(value['settings'], value['prompt'],
                                    structured=value['structured'], timeout=value['timeout'],
                                    on_delta=(lambda text: emit('delta',text)) if value['stream'] else None)
        emit('result',result)
    except Problem as exc:
        emit('error',str(exc))
    except Exception:
        emit('error','模型接口未返回有效内容，请检查接入配置')


if __name__ == '__main__':
    main()
