"""Image insertion into Word documents."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from io import BytesIO

from lxml import etree
from PIL import Image

from app.config import Settings
from app.core.namespaces import A_NS, PIC_NS, WP_NS, W_NS, w_tag
from app.services.word import bookmarks, metadata
from app.services.word.document_package import DOCUMENT_XML, DocxPackage


@dataclass
class InsertImageRequest:
    document_path: str
    insert_before_bookmark: str
    image_bytes: bytes
    filename: str
    caption: str = ""
    font_size: int = 13
    caption_bold: bool = True
    caption_placement: str = "bottom"
    caption_alignment: str = "center"
    highlight: bool = False
    track_in_history: bool = False


EMU_PER_INCH = 914400


def _image_ext(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    return ext if ext in ("png", "jpg", "jpeg", "gif", "bmp") else "png"


def _create_image_paragraph(rel_id: str, width_emu: int, height_emu: int, name: str) -> etree._Element:
    para = etree.Element(w_tag("p"))
    run = etree.SubElement(para, w_tag("r"))
    drawing = etree.SubElement(run, w_tag("drawing"))

    inline = etree.SubElement(
        drawing,
        f"{{{WP_NS}}}inline",
        distT="0",
        distB="0",
        distL="0",
        distR="0",
    )
    extent = etree.SubElement(inline, f"{{{WP_NS}}}extent")
    extent.set("cx", str(width_emu))
    extent.set("cy", str(height_emu))

    doc_pr = etree.SubElement(inline, f"{{{WP_NS}}}docPr")
    doc_pr.set("id", "1")
    doc_pr.set("name", name)

    graphic = etree.SubElement(inline, f"{{{A_NS}}}graphic")
    graphic_data = etree.SubElement(
        graphic,
        f"{{{A_NS}}}graphicData",
        uri="http://schemas.openxmlformats.org/drawingml/2006/picture",
    )
    pic = etree.SubElement(graphic_data, f"{{{PIC_NS}}}pic")
    nv = etree.SubElement(pic, f"{{{PIC_NS}}}nvPicPr")
    c_nv = etree.SubElement(nv, f"{{{PIC_NS}}}cNvPr")
    c_nv.set("id", "0")
    c_nv.set("name", name)
    etree.SubElement(nv, f"{{{PIC_NS}}}cNvPicPr")
    blip_fill = etree.SubElement(pic, f"{{{PIC_NS}}}blipFill")
    blip = etree.SubElement(blip_fill, f"{{{A_NS}}}blip")
    blip.set(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed",
        rel_id,
    )
    stretch = etree.SubElement(blip_fill, f"{{{A_NS}}}stretch")
    etree.SubElement(stretch, f"{{{A_NS}}}fillRect")
    sp_pr = etree.SubElement(pic, f"{{{PIC_NS}}}spPr")
    xfrm = etree.SubElement(sp_pr, f"{{{A_NS}}}xfrm")
    off = etree.SubElement(xfrm, f"{{{A_NS}}}off")
    off.set("x", "0")
    off.set("y", "0")
    ext = etree.SubElement(xfrm, f"{{{A_NS}}}ext")
    ext.set("cx", str(width_emu))
    ext.set("cy", str(height_emu))
    prst_geom = etree.SubElement(sp_pr, f"{{{A_NS}}}prstGeom")
    prst_geom.set("prst", "rect")
    etree.SubElement(prst_geom, f"{{{A_NS}}}avLst")
    return para


def _caption_paragraph(text: str, bold: bool, font_size: int, alignment: str) -> etree._Element:
    para = etree.Element(w_tag("p"))
    ppr = etree.SubElement(para, w_tag("pPr"))
    jc = etree.SubElement(ppr, w_tag("jc"))
    align_map = {"left": "left", "center": "center", "right": "right"}
    jc.set(w_tag("val"), align_map.get(alignment.lower(), "center"))
    run = etree.SubElement(para, w_tag("r"))
    rpr = etree.SubElement(run, w_tag("rPr"))
    if bold:
        etree.SubElement(rpr, w_tag("b"))
    sz = etree.SubElement(rpr, w_tag("sz"))
    sz.set(w_tag("val"), str(font_size * 2))
    t = etree.SubElement(run, w_tag("t"))
    t.text = text
    return para


class ImageService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def insert_image(self, request: InsertImageRequest) -> bool:
        ext = _image_ext(request.filename)
        with Image.open(BytesIO(request.image_bytes)) as img:
            width_px, height_px = img.size
        # Scale to ~6 inches max width
        max_emu = int(6 * EMU_PER_INCH)
        width_emu = int(width_px * 9525)
        height_emu = int(height_px * 9525)
        if width_emu > max_emu:
            ratio = max_emu / width_emu
            width_emu = max_emu
            height_emu = int(height_emu * ratio)

        with DocxPackage(request.document_path).edit_copy() as pkg:
            body = pkg.body
            heading_styles = bookmarks.get_heading_style_map(pkg)
            section = bookmarks.get_section_number_from_bookmark(
                body, request.insert_before_bookmark, heading_styles
            )
            anchor = bookmarks.find_bookmark_paragraph(body, request.insert_before_bookmark)
            if anchor is None:
                return False

            _, rel_id = pkg.add_media_part(ext, request.image_bytes)
            image_para = _create_image_paragraph(
                rel_id, width_emu, height_emu, request.filename
            )
            caption_para = None
            if request.caption:
                caption_para = _caption_paragraph(
                    request.caption,
                    request.caption_bold,
                    request.font_size,
                    request.caption_alignment,
                )

            logical_id = uuid.uuid4().hex[:8]
            start_id = bookmarks.get_next_bookmark_id(body)
            end_id = start_id + 1
            start_bm_s, start_bm_e = bookmarks.create_zero_length_bookmark(
                f"Insert_Start_{logical_id}", start_id
            )
            end_bm_s, end_bm_e = bookmarks.create_zero_length_bookmark(
                f"Insert_End_{logical_id}", end_id
            )

            to_insert: list = [start_bm_s, start_bm_e]
            if request.caption_placement.lower() == "top" and caption_para is not None:
                to_insert.append(caption_para)
            to_insert.append(image_para)
            if request.caption_placement.lower() != "top" and caption_para is not None:
                to_insert.append(caption_para)
            to_insert.extend([end_bm_s, end_bm_e])

            bookmarks.insert_elements_before(anchor, to_insert)
            metadata.add_insert_paragraph_metadata(
                pkg, logical_id, request.document_path, section
            )
            pkg.set_xml(DOCUMENT_XML, pkg.document)
        return True
