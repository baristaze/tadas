"""What a file list answers with: one page, and whether another follows.
The manager asks storage for one row more than the page and keeps it out."""

from tadas.om.base import OmBase
from tadas.om.media.types.file import File


class FilePage(OmBase):
    items: tuple[File, ...]
    has_more: bool
