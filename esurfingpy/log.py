import logging
import os
from logging.handlers import RotatingFileHandler

from rich.logging import RichHandler

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%Y-%m-%d %H:%M:%S]",
    handlers=[RichHandler(
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )]
)

logger = logging.getLogger("rich")


class PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, self.mode, encoding=self.encoding, errors=self.errors)


def configure_file(path):
    """保留最近的故障记录，当前文件和轮转文件均只允许当前用户读取。"""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, PrivateRotatingFileHandler):
            root.removeHandler(handler)
            handler.close()
    handler = PrivateRotatingFileHandler(str(path), maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root.addHandler(handler)


def debug(msg, *args, **kwargs):
    logger.debug(msg, *args, **kwargs)
    return msg


def info(msg, *args, **kwargs):
    logger.info(msg, *args, **kwargs)
    return msg


def warning(msg, *args, **kwargs):
    logger.warning(msg, *args, **kwargs)
    return msg


def error(msg, *args, **kwargs):
    logger.error(msg, *args, **kwargs)
    return msg


def critical(msg, *args, **kwargs):
    logger.critical(msg, *args, **kwargs)
    return msg
