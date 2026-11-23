from functools import lru_cache


@lru_cache(maxsize=1)
def _engine():
    import ddddocr
    return ddddocr.DdddOcr(show_ad=False)


def ocr_image(img: any) -> (bool, str):
    """通过 ddddocr 识别文字"""
    try:
        res = _engine().classification(img)
        return True, res
    except Exception as exc:
        return False, str(exc)
