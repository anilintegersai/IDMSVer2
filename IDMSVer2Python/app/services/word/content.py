"""Content insertion at the end of sections (HTML + images)."""

from __future__ import annotations

import base64
import logging
import uuid
from dataclasses import dataclass

from lxml import etree

from app.config import Settings
from app.core.exceptions import BookmarkNotFoundError
from app.core.namespaces import A_NS, PIC_NS, WP_NS, NSMAP, w_tag
from app.services.word import bookmarks, metadata
from app.services.word.document_package import DOCUMENT_XML, DocxPackage
from app.services.word.paragraph import _html_to_paragraphs, _text_paragraph

logger = logging.getLogger(__name__)


@dataclass
class InsertContentRequest:
    document_path: str
    section_bookmark: str
    html_content: str = ""
    image_data: str | None = None
    image_caption: str | None = None
    image_width: float | None = None
    image_height: float | None = None
    highlight: bool = False
    save_as_copy: bool = False
    copy_name: str | None = None
    track_in_history: bool = False
    update_toc: bool = False


class ContentService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def insert_content(self, request: InsertContentRequest) -> tuple[str, bool]:
        """Insert HTML content and/or image at the end of a section.
        
        Returns (output_path, created_copy) tuple.
        """
        shade = self.settings.shade_fill if request.highlight else None
        
        # Determine output path
        if request.save_as_copy:
            if not request.copy_name:
                raise ValueError("copy_name is required when save_as_copy is true")
            import os
            from pathlib import Path
            base_dir = os.path.dirname(request.document_path)
            copy_name = request.copy_name
            if not copy_name.lower().endswith(".docx"):
                copy_name += ".docx"
            # Strip any path components to keep copy in source folder
            copy_name = os.path.basename(copy_name)
            output_path = os.path.join(base_dir, copy_name)
            created_copy = True
        else:
            output_path = None
            created_copy = False

        with DocxPackage(request.document_path).edit_copy(
            destination=output_path
        ) as pkg:
            body = pkg.body
            heading_styles = bookmarks.get_heading_style_map(pkg)
            
            # Find the section's bookmark paragraph
            section_para = bookmarks.find_bookmark_paragraph(body, request.section_bookmark)
            if section_para is None:
                raise BookmarkNotFoundError(f"Section bookmark not found: {request.section_bookmark}")
            
            # Find the next heading at the same or higher level (the stop boundary)
            section_level = bookmarks._heading_level(section_para, heading_styles)
            if section_level is None:
                section_level = 1
            stop_para = None
            found_section = False
            
            for para in body.iter(w_tag("p")):
                if para is section_para:
                    found_section = True
                    continue
                if found_section:
                    para_level = bookmarks._heading_level(para, heading_styles)
                    if para_level is not None and para_level <= section_level:
                        stop_para = para
                        break
            
            # Create logical ID for tracking
            logical_id = uuid.uuid4().hex[:8]
            start_id = bookmarks.get_next_bookmark_id(body)
            end_id = start_id + 1
            start_bm_s, start_bm_e = bookmarks.create_zero_length_bookmark(
                f"Content_Start_{logical_id}", start_id
            )
            end_bm_s, end_bm_e = bookmarks.create_zero_length_bookmark(
                f"Content_End_{logical_id}", end_id
            )
            
            # Prepare content elements
            to_insert: list = [start_bm_s, start_bm_e]
            
            # Add HTML content paragraphs
            if request.html_content:
                html_paras = _html_to_paragraphs(request.html_content, shade)
                to_insert.extend(html_paras)
            
            # Add image if provided
            if request.image_data:
                image_result = self._create_image_paragraph(
                    pkg, request.image_data, request.image_caption, shade,
                    request.image_width, request.image_height
                )
                # _create_image_paragraph returns a list when there's a caption, otherwise a single element
                if isinstance(image_result, list):
                    to_insert.extend(image_result)
                else:
                    to_insert.append(image_result)
            
            to_insert.extend([end_bm_s, end_bm_e])
            
            # Insert content before the stop paragraph (or at end of body if no stop)
            if stop_para is not None:
                bookmarks.insert_elements_before(stop_para, to_insert)
            else:
                bookmarks.append_elements_before_sectpr(body, to_insert)
            
            # Add metadata
            metadata.add_insert_paragraph_metadata(
                pkg, logical_id, request.document_path, 
                bookmarks.get_section_number_from_bookmark(body, request.section_bookmark, heading_styles)
            )
            
            pkg.set_xml(DOCUMENT_XML, pkg.document)
        
        actual_output_path = output_path if output_path else request.document_path
        
        # Update TOC via COM automation if requested
        if request.update_toc:
            from app.services.word.section import update_toc_via_com
            update_toc_via_com(actual_output_path)
        
        return actual_output_path, created_copy
    
    def _create_image_paragraph(
        self, 
        pkg: DocxPackage, 
        image_data: str, 
        caption: str | None, 
        shade: str | None,
        width_inches: float | None = None,
        height_inches: float | None = None
    ) -> etree._Element | list:
        """Create a paragraph containing an image with optional caption."""
        # Parse base64 data URL
        if image_data.startswith("data:"):
            # Format: data:image/png;base64,iVBORw0KGgo...
            header, data = image_data.split(",", 1)
            mime_type = header.split(":")[1].split(";")[0]
            ext = mime_type.split("/")[-1]
            image_bytes = base64.b64decode(data)
        else:
            # Assume raw base64
            image_bytes = base64.b64decode(image_data)
            ext = "png"
        
        # Add image to document
        part_path, rel_id = pkg.add_media_part(ext, image_bytes)
        
        # Use provided dimensions or defaults (5 inches wide, 3.75 inches tall)
        EMU_PER_INCH = 914400
        width_emu = int((width_inches or 5) * EMU_PER_INCH)
        height_emu = int((height_inches or 3.75) * EMU_PER_INCH)
        
        # Create paragraph with image using the working structure from image.py
        para = etree.Element(w_tag("p"))
        # Don't add shading to image paragraph - only to caption
        # This matches the working image service behavior
        
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
        doc_pr.set("name", "Image")
        
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
        c_nv.set("name", "Image")
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
        
        # Add caption paragraph if provided
        if caption:
            caption_para = etree.Element(w_tag("p"))
            if shade:
                from app.services.word.paragraph import _shading_properties
                caption_para.append(_shading_properties(shade))
            
            # Center alignment
            ppr = etree.SubElement(caption_para, w_tag("pPr"))
            jc = etree.SubElement(ppr, w_tag("jc"), {w_tag("val"): "center"})
            
            # Add caption text
            run = etree.SubElement(caption_para, w_tag("r"))
            rpr = etree.SubElement(run, w_tag("rPr"))
            etree.SubElement(rpr, w_tag("i"))  # Italic for caption
            t = etree.SubElement(run, w_tag("t"))
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            t.text = f"Figure: {caption}"
            
            # Return both image and caption as a list
            return [para, caption_para]
        
        return para
