#!/usr/bin/env python3
"""Generate eval fixture databases for the drupal-migrate plugin.

Each fixture directory under ``evals/fixtures/<name>/`` holds a ``spec.json``.
This script reads the spec and writes two files next to it, from the same
in-memory model, so they can never disagree:

- ``dump.sql``       the MariaDB dump imported by ``fixture up <name>``
- ``expected.json``  the ground truth the eval graders read

Standard library only; safe to run with ``python3 -I``. Output is
deterministic: a fixed seed drives every random choice, rows are emitted in a
fixed order, and the only timestamps derive from the ``epoch`` in the spec.

Usage:
    generate.py [NAME ...]          regenerate the named fixtures (default: all)
    generate.py --check [NAME ...]  exit 1 when committed files differ from a
                                    fresh generation (nothing is written)
    generate.py --version           print the generator version
"""

import argparse
import difflib
import json
import random
import re
import sys
import uuid
from pathlib import Path

GENERATOR_VERSION = "1"
FIXTURES_DIR = Path(__file__).resolve().parent
READER_USER = "reader"
READER_PASSWORD = "reader"
CHARSET = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"
INSERT_BATCH = 200


# ---------------------------------------------------------------------------
# PHP serialization (Drupal 8+ stores config as PHP-serialized arrays)
# ---------------------------------------------------------------------------

def php_serialize(value):
    """Serialize a Python value the way PHP's serialize() does."""
    if value is None:
        return "N;"
    if value is True:
        return "b:1;"
    if value is False:
        return "b:0;"
    if isinstance(value, int):
        return "i:%d;" % value
    if isinstance(value, float):
        return "d:%s;" % repr(value)
    if isinstance(value, str):
        return 's:%d:"%s";' % (len(value.encode("utf-8")), value)
    if isinstance(value, (list, tuple)):
        items = "".join(php_serialize(i) + php_serialize(v) for i, v in enumerate(value))
        return "a:%d:{%s}" % (len(value), items)
    if isinstance(value, dict):
        items = "".join(php_serialize(k) + php_serialize(v) for k, v in value.items())
        return "a:%d:{%s}" % (len(value), items)
    raise TypeError("cannot PHP-serialize %r" % type(value))


# ---------------------------------------------------------------------------
# SQL rendering
# ---------------------------------------------------------------------------

def sql_literal(value):
    if value is None:
        return "NULL"
    if value is True:
        return "1"
    if value is False:
        return "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\0", "\\0")
        )
        return "'%s'" % escaped
    raise TypeError("cannot render %r as SQL" % type(value))


class Table:
    """A table definition plus its rows, rendered as DROP/CREATE/INSERT."""

    def __init__(self, name, columns, primary_key=None, indexes=None):
        self.name = name
        self.columns = columns  # list of (column_name, ddl_type)
        self.primary_key = primary_key or []
        self.indexes = indexes or []
        self.rows = []

    def add(self, **values):
        unknown = set(values) - {c for c, _ in self.columns}
        if unknown:
            raise KeyError("%s: unknown column(s) %s" % (self.name, sorted(unknown)))
        self.rows.append(values)

    def render(self):
        out = ["DROP TABLE IF EXISTS `%s`;" % self.name]
        parts = ["  `%s` %s" % (c, t) for c, t in self.columns]
        if self.primary_key:
            parts.append("  PRIMARY KEY (%s)" % ", ".join("`%s`" % c for c in self.primary_key))
        for idx_name, idx_cols in self.indexes:
            parts.append("  KEY `%s` (%s)" % (idx_name, ", ".join("`%s`" % c for c in idx_cols)))
        out.append("CREATE TABLE `%s` (\n%s\n) %s;" % (self.name, ",\n".join(parts), CHARSET))
        if self.rows:
            names = [c for c, _ in self.columns]
            col_list = ", ".join("`%s`" % c for c in names)
            for start in range(0, len(self.rows), INSERT_BATCH):
                chunk = self.rows[start:start + INSERT_BATCH]
                tuples = []
                for row in chunk:
                    tuples.append("(%s)" % ", ".join(sql_literal(row.get(c)) for c in names))
                out.append("INSERT INTO `%s` (%s) VALUES\n%s;" % (self.name, col_list, ",\n".join(tuples)))
        return "\n".join(out) + "\n"


class Schema:
    def __init__(self):
        self.tables = {}

    def table(self, name, columns, primary_key=None, indexes=None):
        if name in self.tables:
            return self.tables[name]
        table = Table(name, columns, primary_key, indexes)
        self.tables[name] = table
        return table

    def render(self):
        return "".join(self.tables[name].render() + "\n" for name in sorted(self.tables))


def render_dump(spec, schema):
    db = spec["database"]
    header = [
        "-- drupal-migrate eval fixture `%s` (kind: %s)" % (spec["name"], spec["kind"]),
        "-- Generated by evals/fixtures/generate.py version %s from spec.json." % GENERATOR_VERSION,
        "-- DO NOT EDIT: regenerate with `fixture generate %s`." % spec["name"],
        "-- Synthetic data only. All hosts are under reserved documentation domains.",
        "",
        "SET NAMES utf8mb4;",
        "SET FOREIGN_KEY_CHECKS = 0;",
        "SET sql_mode = 'NO_AUTO_VALUE_ON_ZERO';",
        "",
        "CREATE DATABASE IF NOT EXISTS `%s` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;" % db,
        "USE `%s`;" % db,
        "",
        "-- Read-only user handed to the plugin through `fixture query`.",
        "CREATE USER IF NOT EXISTS '%s'@'%%' IDENTIFIED BY '%s';" % (READER_USER, READER_PASSWORD),
        "REVOKE ALL PRIVILEGES, GRANT OPTION FROM '%s'@'%%';" % READER_USER,
        "GRANT SELECT ON `%s`.* TO '%s'@'%%';" % (db, READER_USER),
        "FLUSH PRIVILEGES;",
        "",
    ]
    return "\n".join(header) + schema.render()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class Counter:
    def __init__(self, start=1):
        self.value = start - 1

    def next(self):
        self.value += 1
        return self.value


def det_uuid(rng):
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def pct(populated, total):
    return round(100.0 * populated / total, 1) if total else 0.0


def choose_populated(rng, ids, population):
    """Return the sorted subset of ``ids`` that a field populates."""
    ids = sorted(ids)
    n = int(round(len(ids) * float(population)))
    if n <= 0:
        return []
    if n >= len(ids):
        return ids
    return sorted(rng.sample(ids, n))


FIELD_COLUMNS = {
    "string": [("value", "varchar(255) DEFAULT NULL")],
    "text_long": [("value", "longtext DEFAULT NULL"), ("format", "varchar(255) DEFAULT NULL")],
    "text_with_summary": [
        ("value", "longtext DEFAULT NULL"),
        ("summary", "longtext DEFAULT NULL"),
        ("format", "varchar(255) DEFAULT NULL"),
    ],
    "entity_reference": [("target_id", "int(10) unsigned NOT NULL")],
    "entity_reference_revisions": [
        ("target_id", "int(10) unsigned NOT NULL"),
        ("target_revision_id", "int(10) unsigned NOT NULL"),
    ],
}

FIELD_MODULE = {
    "string": "core",
    "text_long": "text",
    "text_with_summary": "text",
    "entity_reference": "core",
    "entity_reference_revisions": "entity_reference_revisions",
}


# ---------------------------------------------------------------------------
# Drupal 8+ builder
# ---------------------------------------------------------------------------

def field_table_columns(field_name, field_type):
    base = [
        ("bundle", "varchar(128) NOT NULL DEFAULT ''"),
        ("deleted", "tinyint(4) NOT NULL DEFAULT 0"),
        ("entity_id", "int(10) unsigned NOT NULL"),
        ("revision_id", "int(10) unsigned NOT NULL"),
        ("langcode", "varchar(32) NOT NULL DEFAULT ''"),
        ("delta", "int(10) unsigned NOT NULL"),
    ]
    values = [("%s_%s" % (field_name, suffix), ddl) for suffix, ddl in FIELD_COLUMNS[field_type]]
    return base + values


def leaf_value(field_name, field_type, entity_label, langcode):
    """Deterministic content for a populated leaf field value."""
    lang_tag = "" if langcode == "en" else " (%s)" % langcode
    if field_type == "string":
        return {"value": "%s %s%s" % (field_name.replace("field_", "").title(), entity_label, lang_tag)}
    if field_type == "text_long":
        return {"value": "<p>%s text for %s%s.</p>" % (field_name, entity_label, lang_tag), "format": "basic_html"}
    if field_type == "text_with_summary":
        return {
            "value": "<p>Body of %s%s.</p>" % (entity_label, lang_tag),
            "summary": "Summary of %s%s." % (entity_label, lang_tag),
            "format": "basic_html",
        }
    raise ValueError("no leaf value generator for %s" % field_type)


def build_drupal8(spec, rng):
    schema = Schema()
    epoch = int(spec["epoch"])
    source = spec["source"]
    languages = list(source["languages"])
    default_lang = source["default_langcode"]
    base_url = source["base_url"]
    node_bundles = spec["node_bundles"]
    para_bundles = spec["paragraph_bundles"]

    expected = {
        "fixture": spec["name"],
        "kind": spec["kind"],
        "generator_version": GENERATOR_VERSION,
        "source": {
            "technology": source["technology"],
            "topology": source["topology"],
            "delivery": source["delivery"],
            "db_key": spec["database"],
            "database": spec["database"],
            "table_prefix": "",
            "drupal_major": source["drupal_major"],
            "detect_version_result": "drupal8+",
            "base_url": base_url,
            "default_langcode": default_lang,
            "languages": languages,
        },
        "modules": {},
        "entities": {"node": {}, "paragraph": {}, "taxonomy_term": {}, "user": {}},
        "content_inventory": {"node": {}},
        "language_coverage": {},
        "examples": {},
        "redirects": {},
        "path_aliases": {},
        "menus": {},
    }

    # -- core tables -------------------------------------------------------
    config = schema.table(
        "config",
        [("collection", "varchar(255) NOT NULL DEFAULT ''"), ("name", "varchar(255) NOT NULL DEFAULT ''"), ("data", "longblob DEFAULT NULL")],
        primary_key=["collection", "name"],
    )
    key_value = schema.table(
        "key_value",
        [("collection", "varchar(128) NOT NULL DEFAULT ''"), ("name", "varchar(128) NOT NULL DEFAULT ''"), ("value", "longblob NOT NULL")],
        primary_key=["collection", "name"],
    )

    def add_config(name, data):
        config.add(collection="", name=name, data=php_serialize(data))

    # core.extension
    modules = list(spec["modules"])
    themes = list(spec["themes"])
    add_config(
        "core.extension",
        {
            "module": {m: 0 for m in sorted(modules)},
            "theme": {t: 0 for t in themes},
            "profile": spec["profile"],
        },
    )
    expected["modules"] = {
        "source": "core.extension",
        "enabled": sorted(modules),
        "count": len(modules),
        "themes": themes,
        "profile": spec["profile"],
    }
    add_config(
        "system.site",
        {
            "uuid": det_uuid(rng),
            "name": spec["site_name"],
            "mail": spec["site_mail"],
            "slogan": "",
            "page": {"403": "", "404": "", "front": "/node/1"},
            "admin_compact_mode": False,
            "weight_select_max": 100,
            "default_langcode": default_lang,
            "mail_notification": None,
        },
    )
    for lang in languages:
        add_config(
            "language.entity.%s" % lang,
            {
                "uuid": det_uuid(rng),
                "langcode": lang,
                "status": True,
                "dependencies": [],
                "id": lang,
                "label": {"en": "English", "it": "Italian"}.get(lang, lang),
                "direction": "ltr",
                "weight": languages.index(lang),
                "locked": False,
            },
        )
    for i, module in enumerate(sorted(modules)):
        key_value.add(collection="system.schema", name=module, value=php_serialize(8000 + i))
    key_value.add(collection="state", name="system.cron_last", value=php_serialize(epoch))
    key_value.add(collection="state", name="install_time", value=php_serialize(epoch - 86400))

    # -- users -------------------------------------------------------------
    users = schema.table(
        "users",
        [("uid", "int(10) unsigned NOT NULL"), ("uuid", "varchar(128) NOT NULL"), ("langcode", "varchar(12) NOT NULL")],
        primary_key=["uid"],
    )
    users_data = schema.table(
        "users_field_data",
        [
            ("uid", "int(10) unsigned NOT NULL"),
            ("langcode", "varchar(12) NOT NULL"),
            ("preferred_langcode", "varchar(12) DEFAULT NULL"),
            ("preferred_admin_langcode", "varchar(12) DEFAULT NULL"),
            ("name", "varchar(60) NOT NULL DEFAULT ''"),
            ("pass", "varchar(255) DEFAULT NULL"),
            ("mail", "varchar(254) DEFAULT NULL"),
            ("timezone", "varchar(32) DEFAULT NULL"),
            ("status", "tinyint(4) NOT NULL DEFAULT 0"),
            ("created", "int(11) NOT NULL DEFAULT 0"),
            ("changed", "int(11) DEFAULT NULL"),
            ("access", "int(11) NOT NULL DEFAULT 0"),
            ("login", "int(11) NOT NULL DEFAULT 0"),
            ("init", "varchar(254) DEFAULT NULL"),
            ("default_langcode", "tinyint(4) NOT NULL DEFAULT 1"),
        ],
        primary_key=["uid", "langcode"],
    )
    users.add(uid=0, uuid=det_uuid(rng), langcode=default_lang)
    users_data.add(**{"uid": 0, "langcode": default_lang, "preferred_langcode": default_lang,
                      "preferred_admin_langcode": None, "name": "", "pass": None, "mail": None,
                      "timezone": None, "status": 0, "created": epoch, "changed": epoch, "access": 0,
                      "login": 0, "init": None, "default_langcode": 1})
    active_users = 0
    for i, user in enumerate(spec["users"], start=1):
        users.add(uid=i, uuid=det_uuid(rng), langcode=default_lang)
        users_data.add(**{"uid": i, "langcode": default_lang, "preferred_langcode": default_lang,
                          "preferred_admin_langcode": None, "name": user["name"],
                          "pass": "$S$fixture-hash-not-a-real-password", "mail": user["mail"],
                          "timezone": "Europe/Rome", "status": int(user["status"]),
                          "created": epoch + i * 60, "changed": epoch + i * 60,
                          "access": epoch + i * 120 if user["status"] else 0,
                          "login": epoch + i * 120 if user["status"] else 0,
                          "init": user["mail"], "default_langcode": 1})
        active_users += int(user["status"])
    expected["entities"]["user"]["user"] = {
        "distinct": len(spec["users"]),
        "active": active_users,
        "rows_including_anonymous": len(spec["users"]) + 1,
        "fields": {},
        "parent_bundles": [],
        "child_bundles": [],
    }

    # -- taxonomy ----------------------------------------------------------
    term_data = schema.table(
        "taxonomy_term_data",
        [("tid", "int(10) unsigned NOT NULL"), ("revision_id", "int(10) unsigned NOT NULL"), ("vid", "varchar(32) NOT NULL"),
         ("uuid", "varchar(128) NOT NULL"), ("langcode", "varchar(12) NOT NULL")],
        primary_key=["tid"],
    )
    term_field_data = schema.table(
        "taxonomy_term_field_data",
        [("tid", "int(10) unsigned NOT NULL"), ("revision_id", "int(10) unsigned NOT NULL"), ("vid", "varchar(32) NOT NULL"),
         ("langcode", "varchar(12) NOT NULL"), ("status", "tinyint(4) NOT NULL DEFAULT 1"), ("name", "varchar(255) NOT NULL"),
         ("description__value", "longtext DEFAULT NULL"), ("description__format", "varchar(255) DEFAULT NULL"),
         ("weight", "int(11) NOT NULL DEFAULT 0"), ("changed", "int(11) DEFAULT NULL"),
         ("default_langcode", "tinyint(4) NOT NULL DEFAULT 1"), ("revision_translation_affected", "tinyint(4) DEFAULT NULL")],
        primary_key=["tid", "langcode"],
    )
    tid_counter = Counter()
    terms_by_vocab = {}
    for vocab, vspec in spec["vocabularies"].items():
        add_config(
            "taxonomy.vocabulary.%s" % vocab,
            {"uuid": det_uuid(rng), "langcode": default_lang, "status": True, "dependencies": [],
             "name": vspec["label"], "vid": vocab, "description": "", "weight": 0, "new_revision": False},
        )
        tids = []
        for weight, name in enumerate(vspec["terms"]):
            tid = tid_counter.next()
            tids.append(tid)
            term_data.add(tid=tid, revision_id=tid, vid=vocab, uuid=det_uuid(rng), langcode=default_lang)
            term_field_data.add(tid=tid, revision_id=tid, vid=vocab, langcode=default_lang, status=1, name=name,
                                description__value=None, description__format=None, weight=weight,
                                changed=epoch + tid, default_langcode=1, revision_translation_affected=1)
        terms_by_vocab[vocab] = tids
        expected["entities"]["taxonomy_term"][vocab] = {
            "distinct": len(tids),
            "active": len(tids),
            "fields": {},
            "parent_bundles": [],
            "child_bundles": [],
        }

    # -- node tables -------------------------------------------------------
    node = schema.table(
        "node",
        [("nid", "int(10) unsigned NOT NULL"), ("vid", "int(10) unsigned DEFAULT NULL"), ("type", "varchar(32) NOT NULL"),
         ("uuid", "varchar(128) NOT NULL"), ("langcode", "varchar(12) NOT NULL")],
        primary_key=["nid"],
    )
    node_data_cols = [
        ("nid", "int(10) unsigned NOT NULL"), ("vid", "int(10) unsigned NOT NULL"), ("type", "varchar(32) NOT NULL"),
        ("langcode", "varchar(12) NOT NULL"), ("status", "tinyint(4) NOT NULL"), ("uid", "int(10) unsigned NOT NULL"),
        ("title", "varchar(255) NOT NULL"), ("created", "int(11) NOT NULL"), ("changed", "int(11) NOT NULL"),
        ("promote", "tinyint(4) NOT NULL"), ("sticky", "tinyint(4) NOT NULL"), ("default_langcode", "tinyint(4) NOT NULL"),
        ("revision_translation_affected", "tinyint(4) DEFAULT NULL"), ("content_translation_source", "varchar(12) DEFAULT NULL"),
        ("content_translation_outdated", "tinyint(4) DEFAULT NULL"),
    ]
    node_field_data = schema.table("node_field_data", node_data_cols, primary_key=["nid", "langcode"],
                                   indexes=[("node__type", ["type"]), ("node__status_type", ["status", "type", "nid"])])
    node_revision = schema.table(
        "node_revision",
        [("nid", "int(10) unsigned NOT NULL"), ("vid", "int(10) unsigned NOT NULL"), ("langcode", "varchar(12) NOT NULL"),
         ("revision_uid", "int(10) unsigned DEFAULT NULL"), ("revision_timestamp", "int(11) DEFAULT NULL"),
         ("revision_log", "longtext DEFAULT NULL"), ("revision_default", "tinyint(4) DEFAULT NULL")],
        primary_key=["vid"],
    )
    node_field_revision = schema.table("node_field_revision", node_data_cols, primary_key=["vid", "langcode"])

    path_alias = schema.table(
        "path_alias",
        [("id", "int(10) unsigned NOT NULL"), ("revision_id", "int(10) unsigned NOT NULL"), ("uuid", "varchar(128) NOT NULL"),
         ("langcode", "varchar(12) NOT NULL"), ("path", "varchar(255) NOT NULL"), ("alias", "varchar(255) NOT NULL"),
         ("status", "tinyint(4) NOT NULL")],
        primary_key=["id"],
        indexes=[("path_alias__alias_langcode_id_status", ["alias", "langcode", "id", "status"])],
    )
    path_alias_revision = schema.table(
        "path_alias_revision",
        [("id", "int(10) unsigned NOT NULL"), ("revision_id", "int(10) unsigned NOT NULL"), ("langcode", "varchar(12) NOT NULL"),
         ("path", "varchar(255) NOT NULL"), ("alias", "varchar(255) NOT NULL"), ("status", "tinyint(4) NOT NULL"),
         ("revision_default", "tinyint(4) DEFAULT NULL")],
        primary_key=["revision_id"],
    )

    # paragraph tables
    para_item = schema.table(
        "paragraphs_item",
        [("id", "int(10) unsigned NOT NULL"), ("revision_id", "int(10) unsigned DEFAULT NULL"), ("type", "varchar(32) NOT NULL"),
         ("uuid", "varchar(128) NOT NULL"), ("langcode", "varchar(12) NOT NULL")],
        primary_key=["id"],
    )
    para_data_cols = [
        ("id", "int(10) unsigned NOT NULL"), ("revision_id", "int(10) unsigned NOT NULL"), ("type", "varchar(32) NOT NULL"),
        ("langcode", "varchar(12) NOT NULL"), ("status", "tinyint(4) NOT NULL"), ("created", "int(11) DEFAULT NULL"),
        ("parent_id", "varchar(255) DEFAULT NULL"), ("parent_type", "varchar(32) DEFAULT NULL"),
        ("parent_field_name", "varchar(32) DEFAULT NULL"), ("behavior_settings", "longtext DEFAULT NULL"),
        ("default_langcode", "tinyint(4) NOT NULL"), ("revision_translation_affected", "tinyint(4) DEFAULT NULL"),
    ]
    para_data = schema.table("paragraphs_item_field_data", para_data_cols, primary_key=["id", "langcode"],
                             indexes=[("paragraphs_item__type", ["type"]), ("paragraphs_item__parent", ["parent_type", "parent_id"])])
    para_revision = schema.table(
        "paragraphs_item_revision",
        [("id", "int(10) unsigned NOT NULL"), ("revision_id", "int(10) unsigned NOT NULL"), ("langcode", "varchar(12) NOT NULL"),
         ("revision_default", "tinyint(4) DEFAULT NULL")],
        primary_key=["revision_id"],
    )
    para_revision_data = schema.table("paragraphs_item_revision_field_data", para_data_cols, primary_key=["revision_id", "langcode"])

    # -- field config + field tables --------------------------------------
    def declare_fields(entity_type, bundle, fields, bundle_label):
        prefix = "node__" if entity_type == "node" else "paragraph__"
        rev_prefix = "node_revision__" if entity_type == "node" else "paragraph_revision__"
        for field_name, fspec in fields.items():
            ftype = fspec["type"]
            storage_name = "field.storage.%s.%s" % (entity_type, field_name)
            if not any(r["name"] == storage_name for r in config.rows):
                storage_settings = {}
                if ftype in ("entity_reference", "entity_reference_revisions"):
                    storage_settings = {"target_type": fspec["target_type"]}
                modules_dep = [entity_type if entity_type == "node" else "paragraphs"]
                if FIELD_MODULE[ftype] != "core":
                    modules_dep.append(FIELD_MODULE[ftype])
                if ftype in ("entity_reference", "entity_reference_revisions") and fspec["target_type"] == "taxonomy_term":
                    modules_dep.append("taxonomy")
                if ftype == "entity_reference_revisions":
                    modules_dep.append("paragraphs")
                add_config(storage_name, {
                    "uuid": det_uuid(rng), "langcode": default_lang, "status": True,
                    "dependencies": {"module": sorted(set(modules_dep))},
                    "id": "%s.%s" % (entity_type, field_name), "field_name": field_name,
                    "entity_type": entity_type, "type": ftype, "settings": storage_settings,
                    "module": FIELD_MODULE[ftype], "locked": False,
                    "cardinality": int(fspec.get("cardinality", 1)),
                    "translatable": bool(fspec.get("translatable", ftype not in ("entity_reference_revisions",))),
                    "indexes": [], "persist_with_no_fields": field_name == "body", "custom_storage": False,
                })
            field_settings = {}
            if ftype == "text_with_summary":
                field_settings = {"display_summary": True, "required_summary": False}
            elif ftype == "entity_reference":
                field_settings = {"handler": "default:%s" % fspec["target_type"],
                                  "handler_settings": {"target_bundles": {b: b for b in fspec["target_bundles"]},
                                                       "sort": {"field": "name", "direction": "asc"},
                                                       "auto_create": False}}
            elif ftype == "entity_reference_revisions":
                kids = sorted(set(fspec["children"]))
                field_settings = {"handler": "default:paragraph",
                                  "handler_settings": {"target_bundles": {b: b for b in kids},
                                                       "negate": 0,
                                                       "target_bundles_drag_drop": {b: {"weight": i, "enabled": True} for i, b in enumerate(kids)}}}
            bundle_config = ("node.type.%s" % bundle) if entity_type == "node" else ("paragraphs.paragraphs_type.%s" % bundle)
            config_dep = [storage_name, bundle_config]
            if ftype == "entity_reference" and fspec["target_type"] == "taxonomy_term":
                config_dep += ["taxonomy.vocabulary.%s" % b for b in fspec["target_bundles"]]
            if ftype == "entity_reference_revisions":
                config_dep += ["paragraphs.paragraphs_type.%s" % b for b in sorted(set(fspec["children"]))]
            add_config("field.field.%s.%s.%s" % (entity_type, bundle, field_name), {
                "uuid": det_uuid(rng), "langcode": default_lang, "status": True,
                "dependencies": {"config": sorted(config_dep), "module": [FIELD_MODULE[ftype]] if FIELD_MODULE[ftype] != "core" else []},
                "id": "%s.%s.%s" % (entity_type, bundle, field_name), "field_name": field_name,
                "entity_type": entity_type, "bundle": bundle, "label": fspec.get("label", field_name.replace("field_", "").replace("_", " ").title()),
                "description": "", "required": False, "translatable": bool(fspec.get("translatable", ftype not in ("entity_reference_revisions",))),
                "default_value": [], "default_value_callback": "", "settings": field_settings, "field_type": ftype,
            })
            cols = field_table_columns(field_name, ftype)
            pk = ["entity_id", "deleted", "delta", "langcode"]
            schema.table(prefix + field_name, cols, primary_key=pk, indexes=[("bundle", ["bundle"]), ("revision_id", ["revision_id"])])
            schema.table(rev_prefix + field_name, cols, primary_key=["entity_id", "revision_id", "deleted", "delta", "langcode"],
                         indexes=[("bundle", ["bundle"]), ("revision_id", ["revision_id"])])

    for bundle, bspec in node_bundles.items():
        add_config("node.type.%s" % bundle, {
            "uuid": det_uuid(rng), "langcode": default_lang, "status": True, "dependencies": [],
            "name": bspec["label"], "type": bundle, "description": "", "help": "", "new_revision": True,
            "preview_mode": 1, "display_submitted": True,
        })
        declare_fields("node", bundle, bspec["fields"], bspec["label"])
    for bundle, bspec in para_bundles.items():
        add_config("paragraphs.paragraphs_type.%s" % bundle, {
            "uuid": det_uuid(rng), "langcode": default_lang, "status": True, "dependencies": [],
            "id": bundle, "label": bspec["label"], "icon_uuid": None, "icon_default": None,
            "description": "", "behavior_plugins": [],
        })
        declare_fields("paragraph", bundle, bspec["fields"], bspec["label"])

    add_config("system.menu.main", {"uuid": det_uuid(rng), "langcode": default_lang, "status": True, "dependencies": [],
                                    "id": "main", "label": "Main navigation", "description": "Site section links", "locked": True})

    def field_rows(entity_type, field_name, bundle, entity_id, revision_id, langcode, delta, values, current):
        prefix = "node__" if entity_type == "node" else "paragraph__"
        rev_prefix = "node_revision__" if entity_type == "node" else "paragraph_revision__"
        row = {"bundle": bundle, "deleted": 0, "entity_id": entity_id, "revision_id": revision_id,
               "langcode": langcode, "delta": delta}
        for suffix, value in values.items():
            row["%s_%s" % (field_name, suffix)] = value
        schema.tables[rev_prefix + field_name].add(**row)
        if current:
            schema.tables[prefix + field_name].add(**row)

    # -- paragraphs (structure first, leaf values later) --------------------
    pid_counter = Counter()
    prid_counter = Counter()
    paragraphs = []  # dicts: id, rid, bundle, parent_type, parent_id, parent_field, root_nid, attached

    def make_paragraph(bundle, parent_type, parent_id, parent_field, root_nid, attached):
        pid = pid_counter.next()
        prid = prid_counter.next()
        record = {"id": pid, "rid": prid, "bundle": bundle, "parent_type": parent_type, "parent_id": parent_id,
                  "parent_field": parent_field, "root_nid": root_nid, "attached": attached}
        paragraphs.append(record)
        para_item.add(id=pid, revision_id=prid, type=bundle, uuid=det_uuid(rng), langcode=default_lang)
        data = {"id": pid, "revision_id": prid, "type": bundle, "langcode": default_lang, "status": 1,
                "created": epoch + 10000 + pid, "parent_id": str(parent_id), "parent_type": parent_type,
                "parent_field_name": parent_field, "behavior_settings": php_serialize([]),
                "default_langcode": 1, "revision_translation_affected": 1}
        para_data.add(**data)
        para_revision.add(id=pid, revision_id=prid, langcode=default_lang, revision_default=1)
        para_revision_data.add(**data)
        for field_name, fspec in para_bundles[bundle]["fields"].items():
            if fspec["type"] != "entity_reference_revisions":
                continue
            for delta, child_bundle in enumerate(fspec["children"]):
                child = make_paragraph(child_bundle, "paragraph", pid, field_name, root_nid, attached)
                field_rows("paragraph", field_name, bundle, pid, prid, default_lang, delta,
                           {"target_id": child["id"], "target_revision_id": child["rid"]}, current=True)
        return record

    # -- nodes -------------------------------------------------------------
    nid_counter = Counter()
    vid_counter = Counter()
    nodes = []  # dicts: nid, bundle, status, vids, langs
    alias_id = Counter()
    uids = [i for i, u in enumerate(spec["users"], start=1) if u["status"]] or [1]

    for bundle, bspec in node_bundles.items():
        count = int(bspec["count"])
        revisions = int(bspec.get("revisions", 1))
        unpublished = int(bspec.get("unpublished", 0))
        langs = [default_lang] + [l for l in bspec.get("languages", [default_lang]) if l != default_lang]
        bundle_nids = []
        # Decide up front which nids populate each entity_reference_revisions
        # field, so the paragraph trees and the field rows exist only for them.
        planned_nids = list(range(nid_counter.value + 1, nid_counter.value + 1 + count))
        err_populated = {
            field_name: set(choose_populated(rng, planned_nids, fspec.get("population", 1.0)))
            for field_name, fspec in bspec["fields"].items()
            if fspec["type"] == "entity_reference_revisions"
        }
        bspec["_err_populated"] = err_populated
        for i in range(1, count + 1):
            nid = nid_counter.next()
            status = 0 if i > count - unpublished else 1
            title = "%s %d" % (bspec["label"], i)
            vids = [vid_counter.next() for _ in range(revisions)]
            current_vid = vids[-1]
            created = epoch + nid * 3600
            uid = uids[(nid - 1) % len(uids)]
            node.add(nid=nid, vid=current_vid, type=bundle, uuid=det_uuid(rng), langcode=default_lang)
            for r, vid in enumerate(vids):
                node_revision.add(nid=nid, vid=vid, langcode=default_lang, revision_uid=uid,
                                  revision_timestamp=created + r * 600, revision_log="Revision %d" % (r + 1),
                                  revision_default=1)
                for lang in langs:
                    row = {"nid": nid, "vid": vid, "type": bundle, "langcode": lang, "status": status, "uid": uid,
                           "title": title if lang == default_lang else "%s (%s)" % (title, lang),
                           "created": created, "changed": created + r * 600, "promote": 1 if bundle == "article" else 0,
                           "sticky": 0, "default_langcode": 1 if lang == default_lang else 0,
                           "revision_translation_affected": 1,
                           "content_translation_source": None if lang == default_lang else default_lang,
                           "content_translation_outdated": 0}
                    node_field_revision.add(**row)
                    if vid == current_vid:
                        node_field_data.add(**row)
            record = {"nid": nid, "bundle": bundle, "status": status, "vids": vids, "langs": langs, "title": title, "uid": uid}
            nodes.append(record)
            bundle_nids.append(nid)
            # aliases
            for lang in langs:
                slug_root = bspec["alias_prefix"][lang]
                aid = alias_id.next()
                alias = "/%s/%s" % (slug_root, slugify(title if lang == default_lang else "%s-%s" % (title, lang)))
                path_alias.add(id=aid, revision_id=aid, uuid=det_uuid(rng), langcode=lang, path="/node/%d" % nid, alias=alias, status=1)
                path_alias_revision.add(id=aid, revision_id=aid, langcode=lang, path="/node/%d" % nid, alias=alias, status=1, revision_default=1)
                record.setdefault("aliases", {})[lang] = alias
            # ERR fields on the node: build paragraph trees for every revision (same tree, current only once)
            for field_name, fspec in bspec["fields"].items():
                if fspec["type"] != "entity_reference_revisions" or nid not in err_populated[field_name]:
                    continue
                children = []
                for delta, child_bundle in enumerate(fspec["children"]):
                    child = make_paragraph(child_bundle, "node", nid, field_name, nid, True)
                    children.append(child)
                for r, vid in enumerate(vids):
                    for lang in langs:
                        for delta, child in enumerate(children):
                            field_rows("node", field_name, bundle, nid, vid, lang, delta,
                                       {"target_id": child["id"], "target_revision_id": child["rid"]},
                                       current=(vid == current_vid))
        bspec["_nids"] = bundle_nids

    # orphans: paragraphs whose declared parent no longer references them
    for bundle, bspec in para_bundles.items():
        for _ in range(int(bspec.get("orphans", 0))):
            host = bspec["orphan_parent"]  # e.g. {"type": "paragraph", "bundle": "section", "field": "field_items"}
            candidates = [p for p in paragraphs if p["bundle"] == host["bundle"]] if host["type"] == "paragraph" else None
            if host["type"] == "paragraph":
                parent = candidates[-1]
                make_paragraph(bundle, "paragraph", parent["id"], host["field"], None, False)
            else:
                parent_nid = node_bundles[host["bundle"]]["_nids"][-1]
                make_paragraph(bundle, "node", parent_nid, host["field"], None, False)

    # -- leaf field values (exact population) ------------------------------
    nodes_by_nid = {n["nid"]: n for n in nodes}
    for bundle, bspec in node_bundles.items():
        nids = bspec["_nids"]
        fields_expected = {}
        for field_name, fspec in bspec["fields"].items():
            ftype = fspec["type"]
            if ftype == "entity_reference_revisions":
                populated = sorted(bspec["_err_populated"][field_name])
                fields_expected[field_name] = {"type": ftype, "populated": len(populated), "population_pct": pct(len(populated), len(nids)),
                                               "target_type": fspec["target_type"], "target_bundles": sorted(set(fspec["children"]))}
                continue
            populated = choose_populated(rng, nids, fspec["population"])
            for nid in populated:
                n = nodes_by_nid[nid]
                for vid in n["vids"]:
                    for lang in n["langs"]:
                        if ftype == "entity_reference":
                            pool = terms_by_vocab[fspec["target_bundles"][0]]
                            picks = [pool[(nid - 1) % len(pool)], pool[(nid + 2) % len(pool)]]
                            for delta, tid in enumerate(sorted(set(picks))):
                                field_rows("node", field_name, bundle, nid, vid, lang, delta, {"target_id": tid}, current=(vid == n["vids"][-1]))
                        else:
                            field_rows("node", field_name, bundle, nid, vid, lang, 0,
                                       leaf_value(field_name, ftype, n["title"], lang), current=(vid == n["vids"][-1]))
            entry = {"type": ftype, "populated": len(populated), "population_pct": pct(len(populated), len(nids))}
            if ftype == "entity_reference":
                entry["target_type"] = fspec["target_type"]
                entry["target_bundles"] = list(fspec["target_bundles"])
            fields_expected[field_name] = entry
        published = [n for n in nodes if n["bundle"] == bundle and n["status"] == 1]
        langs = [default_lang] + [l for l in bspec.get("languages", [default_lang]) if l != default_lang]
        expected["entities"]["node"][bundle] = {
            "label": bspec["label"],
            "distinct": len(nids),
            "active": len(published),
            "unpublished": len(nids) - len(published),
            "revisions_per_entity": int(bspec.get("revisions", 1)),
            "languages": langs,
            "field_data_rows": len(nids) * len(langs),
            "field_revision_rows": len(nids) * len(langs) * int(bspec.get("revisions", 1)),
            "fields": fields_expected,
            "parent_bundles": [],
            "child_bundles": sorted({c for f in bspec["fields"].values() if f["type"] == "entity_reference_revisions" for c in f["children"]}),
        }
        expected["content_inventory"]["node"][bundle] = {"total": len(nids), "published": len(published),
                                                         "languages": {l: len(nids) for l in langs}}
        expected["language_coverage"][bundle] = {l: len(nids) for l in langs}
        first = published[0]
        expected["examples"][bundle] = {"nid": first["nid"], "title": first["title"], "aliases": first["aliases"],
                                        "url": "%s%s" % (base_url, first["aliases"][default_lang])}

    for bundle, bspec in para_bundles.items():
        instances = [p for p in paragraphs if p["bundle"] == bundle]
        ids = [p["id"] for p in instances]
        fields_expected = {}
        for field_name, fspec in bspec["fields"].items():
            ftype = fspec["type"]
            if ftype == "entity_reference_revisions":
                fields_expected[field_name] = {"type": ftype, "populated": len(ids), "population_pct": pct(len(ids), len(ids)),
                                               "target_type": "paragraph", "target_bundles": sorted(set(fspec["children"]))}
                continue
            populated = choose_populated(rng, ids, fspec["population"])
            by_id = {p["id"]: p for p in instances}
            for pid in populated:
                p = by_id[pid]
                field_rows("paragraph", field_name, bundle, pid, p["rid"], default_lang, 0,
                           leaf_value(field_name, ftype, "%s %d" % (bspec["label"], pid), default_lang), current=True)
            fields_expected[field_name] = {"type": ftype, "populated": len(populated), "population_pct": pct(len(populated), len(ids))}
        active = [p for p in instances if p["attached"] and p["root_nid"] and nodes_by_nid[p["root_nid"]]["status"] == 1]
        orphans = [p for p in instances if not p["attached"]]
        parent_bundles = []
        for p in instances:
            if p["parent_type"] == "node":
                pb = {"parent_type": "node", "parent_bundle": nodes_by_nid[int(p["parent_id"])]["bundle"], "field": p["parent_field"]}
            else:
                parent = next(q for q in paragraphs if q["id"] == p["parent_id"])
                pb = {"parent_type": "paragraph", "parent_bundle": parent["bundle"], "field": p["parent_field"]}
            if pb not in parent_bundles:
                parent_bundles.append(pb)
        parent_bundles.sort(key=lambda d: (d["parent_type"], d["parent_bundle"], d["field"]))
        root_bundles = sorted({nodes_by_nid[p["root_nid"]]["bundle"] for p in instances if p["root_nid"]})
        children = sorted({c for f in bspec["fields"].values() if f["type"] == "entity_reference_revisions" for c in f["children"]})
        expected["entities"]["paragraph"][bundle] = {
            "label": bspec["label"],
            "distinct": len(ids),
            "attached": len(ids) - len(orphans),
            "active": len(active),
            "orphans": len(orphans),
            "is_container": bool(children),
            "fields": fields_expected,
            "parent_bundles": parent_bundles,
            "root_node_bundles": root_bundles,
            "child_bundles": children,
        }

    # -- redirects ---------------------------------------------------------
    redirect = schema.table(
        "redirect",
        [("rid", "int(10) unsigned NOT NULL"), ("uuid", "varchar(128) NOT NULL"), ("hash", "varchar(64) NOT NULL"),
         ("type", "varchar(32) NOT NULL"), ("uid", "int(10) unsigned NOT NULL"), ("redirect_source__path", "varchar(2048) DEFAULT NULL"),
         ("redirect_source__query", "longblob DEFAULT NULL"), ("redirect_redirect__uri", "varchar(2048) DEFAULT NULL"),
         ("redirect_redirect__title", "varchar(255) DEFAULT NULL"), ("redirect_redirect__options", "longblob DEFAULT NULL"),
         ("status_code", "smallint(6) DEFAULT NULL"), ("language", "varchar(12) NOT NULL"), ("created", "int(11) DEFAULT NULL")],
        primary_key=["rid"],
    )
    redirect_rows = []
    for i, r in enumerate(spec["redirects"], start=1):
        redirect.add(rid=i, uuid=det_uuid(rng), hash="fixturehash%02d" % i, type="redirect", uid=1,
                     redirect_source__path=r["source"], redirect_source__query=php_serialize([]),
                     redirect_redirect__uri="internal:/node/%d" % r["nid"], redirect_redirect__title="",
                     redirect_redirect__options=php_serialize([]), status_code=int(r.get("status_code", 301)),
                     language=r.get("language", "und"), created=epoch + 20000 + i)
        redirect_rows.append({"source": r["source"], "target": "/node/%d" % r["nid"], "status_code": int(r.get("status_code", 301))})
    expected["redirects"] = {"count": len(redirect_rows), "table": "redirect", "rows": redirect_rows}
    expected["path_aliases"] = {"count": len(path_alias.rows), "table": "path_alias"}

    # -- menu --------------------------------------------------------------
    mlc = schema.table(
        "menu_link_content",
        [("id", "int(10) unsigned NOT NULL"), ("revision_id", "int(10) unsigned DEFAULT NULL"), ("bundle", "varchar(32) NOT NULL"),
         ("uuid", "varchar(128) NOT NULL"), ("langcode", "varchar(12) NOT NULL")],
        primary_key=["id"],
    )
    mlc_data = schema.table(
        "menu_link_content_data",
        [("id", "int(10) unsigned NOT NULL"), ("revision_id", "int(10) unsigned NOT NULL"), ("bundle", "varchar(32) NOT NULL"),
         ("langcode", "varchar(12) NOT NULL"), ("enabled", "tinyint(4) NOT NULL"), ("title", "varchar(255) DEFAULT NULL"),
         ("description", "varchar(255) DEFAULT NULL"), ("menu_name", "varchar(32) DEFAULT NULL"), ("link__uri", "varchar(2048) DEFAULT NULL"),
         ("link__title", "varchar(255) DEFAULT NULL"), ("link__options", "longblob DEFAULT NULL"), ("external", "tinyint(4) DEFAULT NULL"),
         ("rediscover", "tinyint(4) DEFAULT NULL"), ("weight", "int(11) DEFAULT NULL"), ("expanded", "tinyint(4) DEFAULT NULL"),
         ("parent", "varchar(255) DEFAULT NULL"), ("changed", "int(11) DEFAULT NULL"), ("default_langcode", "tinyint(4) NOT NULL"),
         ("revision_translation_affected", "tinyint(4) DEFAULT NULL")],
        primary_key=["id", "langcode"],
    )
    menus_expected = {}
    link_id = Counter()
    for menu_name, links in spec["menus"].items():
        uuids = {}
        for weight, link in enumerate(links):
            lid = link_id.next()
            u = det_uuid(rng)
            uuids[link["title"]] = u
            uri = link.get("uri") or "entity:node/%d" % link["nid"]
            parent_title = link.get("parent")
            mlc.add(id=lid, revision_id=lid, bundle="menu_link_content", uuid=u, langcode=default_lang)
            mlc_data.add(id=lid, revision_id=lid, bundle="menu_link_content", langcode=default_lang, enabled=1,
                         title=link["title"], description=None, menu_name=menu_name, link__uri=uri, link__title="",
                         link__options=php_serialize([]), external=0, rediscover=0, weight=weight, expanded=0,
                         parent=("menu_link_content:%s" % uuids[parent_title]) if parent_title else None,
                         changed=epoch + 30000 + lid, default_langcode=1, revision_translation_affected=1)
        menus_expected[menu_name] = {"links": len(links), "top_level": sum(1 for l in links if not l.get("parent"))}
    expected["menus"] = menus_expected

    # -- table list for signature checks ----------------------------------
    expected["tables"] = sorted(schema.tables)
    expected["signature"] = {"present": ["config", "key_value"], "absent": ["field_config_instance"]}
    for bspec in node_bundles.values():
        bspec.pop("_nids", None)
        bspec.pop("_err_populated", None)
    verify_population(schema, expected)
    return schema, expected


def verify_population(schema, expected):
    """Fail loudly when a field table disagrees with the population expected.json reports."""
    prefixes = {"node": "node__", "paragraph": "paragraph__"}
    for entity_type, prefix in prefixes.items():
        for bundle, bexp in expected["entities"][entity_type].items():
            for field_name, fexp in bexp["fields"].items():
                table = schema.tables[prefix + field_name]
                in_dump = len({row["entity_id"] for row in table.rows if row["bundle"] == bundle})
                if in_dump != fexp["populated"]:
                    raise RuntimeError(
                        "%s.%s.%s: dump has %d populated entities, expected.json says %d"
                        % (entity_type, bundle, field_name, in_dump, fexp["populated"])
                    )


BUILDERS = {"drupal8": build_drupal8}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def generate(name):
    fixture_dir = FIXTURES_DIR / name
    spec_path = fixture_dir / "spec.json"
    if not spec_path.is_file():
        raise SystemExit("%s: no spec.json" % fixture_dir)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["name"] = name
    kind = spec.get("kind")
    if kind not in BUILDERS:
        raise SystemExit("%s: unknown fixture kind %r (known: %s)" % (name, kind, ", ".join(sorted(BUILDERS))))
    rng = random.Random(int(spec["seed"]))
    schema, expected = BUILDERS[kind](spec, rng)
    dump = render_dump(spec, schema)
    expected_text = json.dumps(expected, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    return {"dump.sql": dump, "expected.json": expected_text}


def fixture_names():
    return sorted(p.parent.name for p in FIXTURES_DIR.glob("*/spec.json"))


def check(name, outputs):
    ok = True
    for filename, fresh in outputs.items():
        path = FIXTURES_DIR / name / filename
        if not path.is_file():
            print("%s/%s: missing (run generate.py %s)" % (name, filename, name))
            ok = False
            continue
        committed = path.read_text(encoding="utf-8")
        if committed != fresh:
            ok = False
            diff = list(difflib.unified_diff(committed.splitlines(), fresh.splitlines(),
                                             "committed/%s" % filename, "generated/%s" % filename, lineterm="", n=0))
            print("%s/%s: differs from generated output" % (name, filename))
            for line in diff[:12]:
                print("  " + line)
            if len(diff) > 12:
                print("  ... (%d more diff lines)" % (len(diff) - 12))
    return ok


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="fixture names (default: every directory with a spec.json)")
    parser.add_argument("--check", action="store_true", help="compare committed files with a fresh generation; exit 1 on drift")
    parser.add_argument("--version", action="store_true", help="print the generator version and exit")
    args = parser.parse_args(argv)
    if args.version:
        print(GENERATOR_VERSION)
        return 0
    names = args.names or fixture_names()
    if not names:
        print("no fixture spec found under %s" % FIXTURES_DIR)
        return 1
    all_ok = True
    for name in names:
        outputs = generate(name)
        if args.check:
            if check(name, outputs):
                print("%s: up to date" % name)
            else:
                all_ok = False
            continue
        for filename, text in outputs.items():
            (FIXTURES_DIR / name / filename).write_text(text, encoding="utf-8")
        print("%s: wrote dump.sql (%d bytes) and expected.json (%d bytes)" % (name, len(outputs["dump.sql"]), len(outputs["expected.json"])))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
