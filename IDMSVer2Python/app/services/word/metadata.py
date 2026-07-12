"""Custom XML metadata for inserted/merged content tracking."""

from __future__ import annotations

import io
from datetime import datetime, timezone

from lxml import etree

from app.core.namespaces import CUSTOM_XML_NS, W_NS, w_tag

# A distinctive part name so we never clobber a document's own custom XML.
# Real Office documents already ship customXml/item1.xml..itemN.xml (cover-page
# properties, bibliography, etc.); writing our metadata into item1.xml would
# corrupt them.
CUSTOM_XML_PART = "customXml/idmsInsertMetadata.xml"
CUSTOM_XML_RELS = "customXml/_rels/idmsInsertMetadata.xml.rels"


def _ensure_custom_xml_part(pkg) -> etree._Element:
  if CUSTOM_XML_PART not in pkg.list_parts():
    root = etree.Element(
      f"{{{CUSTOM_XML_NS}}}InsertMetadata",
      nsmap={None: CUSTOM_XML_NS},
    )
    pkg.write_part_bytes(
      CUSTOM_XML_PART,
      etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True),
    )
    _ensure_custom_xml_rels(pkg)
    _register_custom_xml_in_content_types(pkg)
    _link_custom_xml_in_document(pkg)
  data = pkg.read_part_bytes(CUSTOM_XML_PART)
  return etree.fromstring(data)


def _ensure_custom_xml_rels(pkg) -> None:
  rels_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
  root = etree.Element(f"{{{rels_ns}}}Relationships")
  pkg.write_part_bytes(
    CUSTOM_XML_RELS,
    etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True),
  )


def _register_custom_xml_in_content_types(pkg) -> None:
  from app.services.word.document_package import CONTENT_TYPES

  ct = pkg.get_xml(CONTENT_TYPES)
  ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
  override = etree.SubElement(
    ct,
    f"{{{ct_ns}}}Override",
    PartName=f"/{CUSTOM_XML_PART}",
    ContentType="application/xml",
  )
  pkg.set_xml(CONTENT_TYPES, ct)


def _link_custom_xml_in_document(pkg) -> None:
  from app.services.word.document_package import DOC_RELS

  rels_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
  rels = pkg.get_xml(DOC_RELS)
  existing = [r.get("Id", "") for r in rels.findall(f"{{{rels_ns}}}Relationship")]
  nums = [int(x[3:]) for x in existing if x.startswith("rId") and x[3:].isdigit()]
  next_id = f"rId{(max(nums) if nums else 0) + 1}"
  etree.SubElement(
    rels,
    f"{{{rels_ns}}}Relationship",
    Id=next_id,
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml",
    Target=f"../{CUSTOM_XML_PART}",
  )
  pkg.set_xml(DOC_RELS, rels)


def _save_metadata(pkg, root: etree._Element) -> None:
  pkg.write_part_bytes(
    CUSTOM_XML_PART,
    etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True),
  )


def add_merge_metadata(
  pkg,
  logical_id: str,
  source_doc: str,
  source_section: str,
  destination_level: int,
  destination_doc: str,
) -> None:
  ns = CUSTOM_XML_NS
  root = _ensure_custom_xml_part(pkg)
  entry = etree.SubElement(
    root,
    f"{{{ns}}}MergedSection",
    LogicalId=logical_id,
  )
  etree.SubElement(entry, f"{{{ns}}}SourceDocument").text = source_doc
  etree.SubElement(entry, f"{{{ns}}}SourceSection").text = source_section
  etree.SubElement(entry, f"{{{ns}}}DestinationLevel").text = str(destination_level)
  etree.SubElement(entry, f"{{{ns}}}DestinationDocument").text = destination_doc
  etree.SubElement(entry, f"{{{ns}}}InsertedAt").text = datetime.now(timezone.utc).isoformat()
  _save_metadata(pkg, root)


def add_insert_paragraph_metadata(
  pkg, logical_id: str, source_doc: str, section_number: str
) -> None:
  ns = CUSTOM_XML_NS
  root = _ensure_custom_xml_part(pkg)
  entry = etree.SubElement(
    root,
    f"{{{ns}}}InsertedParagraph",
    LogicalId=logical_id,
  )
  etree.SubElement(entry, f"{{{ns}}}SectionNumber").text = section_number
  etree.SubElement(entry, f"{{{ns}}}SourceDocument").text = source_doc
  etree.SubElement(entry, f"{{{ns}}}InsertedAt").text = datetime.now(timezone.utc).isoformat()
  _save_metadata(pkg, root)


def add_insert_section_metadata(
  pkg, logical_id: str, source_doc: str, section_number: str, level: int
) -> None:
  ns = CUSTOM_XML_NS
  root = _ensure_custom_xml_part(pkg)
  entry = etree.SubElement(
    root,
    f"{{{ns}}}InsertedSection",
    LogicalId=logical_id,
  )
  etree.SubElement(entry, f"{{{ns}}}SectionNumber").text = section_number
  etree.SubElement(entry, f"{{{ns}}}Level").text = str(level)
  etree.SubElement(entry, f"{{{ns}}}SourceDocument").text = source_doc
  etree.SubElement(entry, f"{{{ns}}}InsertedAt").text = datetime.now(timezone.utc).isoformat()
  _save_metadata(pkg, root)


def read_metadata(pkg) -> etree._Element | None:
  if CUSTOM_XML_PART not in pkg.list_parts():
    return None
  return etree.fromstring(pkg.read_part_bytes(CUSTOM_XML_PART))
