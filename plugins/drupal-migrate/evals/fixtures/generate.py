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

GENERATOR_VERSION = "2"
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
        active_ids = {p["id"] for p in active}
        active_children = [c for c in paragraphs if c["parent_type"] == "paragraph" and c["parent_id"] in {p["id"] for p in instances}
                           and c["attached"] and c["root_nid"] and nodes_by_nid[c["root_nid"]]["status"] == 1]
        expected["entities"]["paragraph"][bundle] = {
            "label": bspec["label"],
            "distinct": len(ids),
            "attached": len(ids) - len(orphans),
            "active": len(active),
            "inactive": len(ids) - len(active),
            "active_children": len(active_children) if children else 0,
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
    # The fixture declares no external integration (no connector config, no API endpoint),
    # so the ecosystem map must report none.
    expected["integrations"] = []
    expected["integration_count"] = 0
    expected["tables"] = sorted(schema.tables)
    expected["signature"] = {"present": ["config", "key_value"], "absent": ["field_config_instance"]}
    for bspec in node_bundles.values():
        bspec.pop("_nids", None)
        bspec.pop("_err_populated", None)
    verify_population(schema, expected)
    return schema, expected


def verify_population(schema, expected, prefixes=None):
    """Fail loudly when a field table disagrees with the population expected.json reports."""
    prefixes = prefixes or {"node": "node__", "paragraph": "paragraph__"}
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


# ---------------------------------------------------------------------------
# Drupal 7 builder
# ---------------------------------------------------------------------------

D7_FIELD_COLUMNS = {
    "text": [("value", "varchar(255) DEFAULT NULL"), ("format", "varchar(255) DEFAULT NULL")],
    "text_long": [("value", "longtext DEFAULT NULL"), ("format", "varchar(255) DEFAULT NULL")],
    "text_with_summary": [
        ("value", "longtext DEFAULT NULL"),
        ("summary", "longtext DEFAULT NULL"),
        ("format", "varchar(255) DEFAULT NULL"),
    ],
    "taxonomy_term_reference": [("tid", "int(10) unsigned DEFAULT NULL")],
    "paragraphs": [("value", "int(10) unsigned DEFAULT NULL"), ("revision_id", "int(10) unsigned DEFAULT NULL")],
}

D7_FIELD_MODULE = {
    "text": "text",
    "text_long": "text",
    "text_with_summary": "text",
    "taxonomy_term_reference": "taxonomy",
    "paragraphs": "paragraphs",
}


def d7_field_columns(field_name, field_type):
    base = [
        ("entity_type", "varchar(128) NOT NULL DEFAULT ''"),
        ("bundle", "varchar(128) NOT NULL DEFAULT ''"),
        ("deleted", "tinyint(4) NOT NULL DEFAULT 0"),
        ("entity_id", "int(10) unsigned NOT NULL"),
        ("revision_id", "int(10) unsigned DEFAULT NULL"),
        ("language", "varchar(32) NOT NULL DEFAULT ''"),
        ("delta", "int(10) unsigned NOT NULL"),
    ]
    values = [("%s_%s" % (field_name, suffix), ddl) for suffix, ddl in D7_FIELD_COLUMNS[field_type]]
    return base + values


def d7_leaf_value(field_name, field_type, entity_label):
    if field_type == "text":
        return {"value": "%s %s" % (field_name.replace("field_", "").title(), entity_label), "format": None}
    if field_type == "text_long":
        return {"value": "<p>%s text for %s.</p>" % (field_name, entity_label), "format": "filtered_html"}
    if field_type == "text_with_summary":
        return {"value": "<p>Body of %s.</p>" % entity_label, "summary": "Summary of %s." % entity_label, "format": "filtered_html"}
    raise ValueError("no Drupal 7 leaf value generator for %s" % field_type)


def build_drupal7_taxonomy(spec, schema, expected, tid_counter):
    vocab_table = schema.table(
        "taxonomy_vocabulary",        [("vid", "int(10) unsigned NOT NULL"), ("name", "varchar(255) NOT NULL DEFAULT ''"), ("machine_name", "varchar(255) NOT NULL DEFAULT ''"),
         ("description", "longtext DEFAULT NULL"), ("hierarchy", "tinyint(3) unsigned NOT NULL DEFAULT 0"), ("module", "varchar(255) NOT NULL DEFAULT ''"),
         ("weight", "int(11) NOT NULL DEFAULT 0")],
        primary_key=["vid"],
    )
    term_table = schema.table(
        "taxonomy_term_data",
        [("tid", "int(10) unsigned NOT NULL"), ("vid", "int(10) unsigned NOT NULL DEFAULT 0"), ("name", "varchar(255) NOT NULL DEFAULT ''"),
         ("description", "longtext DEFAULT NULL"), ("format", "varchar(255) DEFAULT NULL"), ("weight", "int(11) NOT NULL DEFAULT 0")],
        primary_key=["tid"],
    )
    for vid, (machine, vspec) in enumerate(spec["vocabularies"].items(), start=1):
        vocab_table.add(vid=vid, name=vspec["label"], machine_name=machine, description="", hierarchy=0, module="taxonomy", weight=0)
        for weight, name in enumerate(vspec["terms"]):
            term_table.add(tid=tid_counter.next(), vid=vid, name=name, description="", format=None, weight=weight)
        expected["entities"]["taxonomy_term"][machine] = {"distinct": len(vspec["terms"]), "active": len(vspec["terms"]),
                                                         "vid": vid, "fields": {}, "parent_bundles": [], "child_bundles": []}


def build_drupal7_menus(spec, schema):
    menu_custom = schema.table(
        "menu_custom",
        [("menu_name", "varchar(32) NOT NULL DEFAULT ''"), ("title", "varchar(255) NOT NULL DEFAULT ''"), ("description", "text DEFAULT NULL")],
        primary_key=["menu_name"],
    )
    menu_links = schema.table(
        "menu_links",
        [("menu_name", "varchar(32) NOT NULL DEFAULT ''"), ("mlid", "int(10) unsigned NOT NULL"), ("plid", "int(10) unsigned NOT NULL DEFAULT 0"),
         ("link_path", "varchar(255) NOT NULL DEFAULT ''"), ("router_path", "varchar(255) NOT NULL DEFAULT ''"),
         ("link_title", "varchar(255) NOT NULL DEFAULT ''"), ("options", "blob DEFAULT NULL"), ("module", "varchar(255) NOT NULL DEFAULT 'system'"),
         ("hidden", "smallint(6) NOT NULL DEFAULT 0"), ("external", "smallint(6) NOT NULL DEFAULT 0"), ("has_children", "smallint(6) NOT NULL DEFAULT 0"),
         ("expanded", "smallint(6) NOT NULL DEFAULT 0"), ("weight", "int(11) NOT NULL DEFAULT 0"), ("depth", "smallint(6) NOT NULL DEFAULT 0"),
         ("customized", "smallint(6) NOT NULL DEFAULT 0"), ("p1", "int(10) unsigned NOT NULL DEFAULT 0"), ("p2", "int(10) unsigned NOT NULL DEFAULT 0")],
        primary_key=["mlid"],
    )
    mlid = Counter()
    menus_expected = {}
    for menu_name, links in spec["menus"].items():
        menu_custom.add(menu_name=menu_name, title=menu_name.replace("-", " ").title(), description="")
        ids = {}
        for weight, link in enumerate(links):
            m = mlid.next()
            ids[link["title"]] = m
            parent = ids.get(link.get("parent"), 0)
            path = link.get("path") or "node/%d" % link["nid"]
            menu_links.add(menu_name=menu_name, mlid=m, plid=parent, link_path=path, router_path="node/%" if path.startswith("node/") else path,
                           link_title=link["title"], options=php_serialize([]), module="menu", hidden=0, external=0,
                           has_children=0, expanded=0, weight=weight, depth=2 if parent else 1, customized=1,
                           p1=parent or m, p2=m if parent else 0)
        menus_expected[menu_name] = {"links": len(links), "top_level": sum(1 for l in links if not l.get("parent"))}
    return menus_expected


def build_drupal7(spec, rng):
    schema = Schema()
    epoch = int(spec["epoch"])
    source = spec["source"]
    base_url = source["base_url"]
    node_language = spec.get("node_language", "und")
    default_lang = source["default_langcode"]
    node_bundles = spec["node_bundles"]
    para_bundles = spec["paragraph_bundles"]
    field_defs = spec["fields"]

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
            "detect_version_result": "drupal7",
            "base_url": base_url,
            "default_langcode": default_lang,
            "node_language": node_language,
            "languages": list(source["languages"]),
        },
        "entities": {"node": {}, "paragraph": {}, "taxonomy_term": {}, "user": {}},
        "content_inventory": {"node": {}},
        "language_coverage": {},
        "examples": {},
        "url_aliases": {},
        "menus": {},
    }

    # -- system + variable ---------------------------------------------------
    system = schema.table(
        "system",
        [("filename", "varchar(255) NOT NULL DEFAULT ''"), ("name", "varchar(255) NOT NULL DEFAULT ''"),
         ("type", "varchar(12) NOT NULL DEFAULT ''"), ("owner", "varchar(255) NOT NULL DEFAULT ''"),
         ("status", "int(11) NOT NULL DEFAULT 0"), ("bootstrap", "int(11) NOT NULL DEFAULT 0"),
         ("schema_version", "smallint(6) NOT NULL DEFAULT -1"), ("weight", "int(11) NOT NULL DEFAULT 0"),
         ("info", "blob DEFAULT NULL")],
        primary_key=["filename"],
    )
    enabled_modules = []
    disabled_modules = []
    for m in spec["modules"]:
        core = m.get("core", False)
        folder = "modules/%s" % m["name"] if core else "sites/all/modules/%s" % m["name"]
        info = {"name": m["name"].replace("_", " ").title(), "package": "Core" if core else "Other",
                "version": "7.%d" % spec.get("core_minor", 103) if core else m.get("version", "7.x-1.0"),
                "core": "7.x", "project": "drupal" if core else m["name"], "dependencies": [], "php": "5.2.4"}
        system.add(filename="%s/%s.module" % (folder, m["name"]), name=m["name"], type="module", owner="",
                   status=int(m["status"]), bootstrap=0, schema_version=7000 if m["status"] else -1,
                   weight=0, info=php_serialize(info))
        (enabled_modules if m["status"] else disabled_modules).append(m["name"])
    for t in spec["themes"]:
        system.add(filename="themes/%s/%s.info" % (t, t), name=t, type="theme", owner="themes/engines/phptemplate/phptemplate.engine",
                   status=1, bootstrap=0, schema_version=-1, weight=0,
                   info=php_serialize({"name": t.title(), "core": "7.x", "engine": "phptemplate"}))
    expected["modules"] = {
        "source": "system",
        "installed": sorted(enabled_modules + disabled_modules),
        "enabled": sorted(enabled_modules),
        "disabled": sorted(disabled_modules),
        "count_installed": len(enabled_modules) + len(disabled_modules),
        "count": len(enabled_modules),
        "themes": list(spec["themes"]),
    }
    variable = schema.table(
        "variable",
        [("name", "varchar(128) NOT NULL DEFAULT ''"), ("value", "longblob NOT NULL")],
        primary_key=["name"],
    )
    variable.add(name="site_name", value=php_serialize(spec["site_name"]))
    variable.add(name="site_mail", value=php_serialize(spec["site_mail"]))
    variable.add(name="theme_default", value=php_serialize(spec["themes"][0]))
    variable.add(name="language_default", value=php_serialize({"language": default_lang, "name": "English", "enabled": 1, "weight": 0}))
    variable.add(name="clean_url", value=php_serialize(1))
    variable.add(name="install_profile", value=php_serialize("standard"))

    # -- users -------------------------------------------------------------
    users = schema.table(
        "users",
        [("uid", "int(10) unsigned NOT NULL"), ("name", "varchar(60) NOT NULL DEFAULT ''"), ("pass", "varchar(128) NOT NULL DEFAULT ''"),
         ("mail", "varchar(254) DEFAULT ''"), ("theme", "varchar(255) NOT NULL DEFAULT ''"), ("signature", "varchar(255) NOT NULL DEFAULT ''"),
         ("signature_format", "varchar(255) DEFAULT NULL"), ("created", "int(11) NOT NULL DEFAULT 0"), ("access", "int(11) NOT NULL DEFAULT 0"),
         ("login", "int(11) NOT NULL DEFAULT 0"), ("status", "tinyint(4) NOT NULL DEFAULT 0"), ("timezone", "varchar(32) DEFAULT NULL"),
         ("language", "varchar(12) NOT NULL DEFAULT ''"), ("picture", "int(11) NOT NULL DEFAULT 0"), ("init", "varchar(254) DEFAULT ''"),
         ("data", "longblob DEFAULT NULL")],
        primary_key=["uid"],
    )
    users.add(**{"uid": 0, "name": "", "pass": "", "mail": "", "theme": "", "signature": "", "signature_format": None,
                 "created": 0, "access": 0, "login": 0, "status": 0, "timezone": None, "language": "", "picture": 0,
                 "init": "", "data": None})
    active_users = 0
    for i, user in enumerate(spec["users"], start=1):
        users.add(**{"uid": i, "name": user["name"], "pass": "$S$fixture-hash-not-a-real-password", "mail": user["mail"],
                     "theme": "", "signature": "", "signature_format": None, "created": epoch + i * 60,
                     "access": epoch + i * 120 if user["status"] else 0, "login": epoch + i * 120 if user["status"] else 0,
                     "status": int(user["status"]), "timezone": "Europe/Rome", "language": "", "picture": 0,
                     "init": user["mail"], "data": None})
        active_users += int(user["status"])
    expected["entities"]["user"]["user"] = {"distinct": len(spec["users"]), "active": active_users,
                                            "rows_including_anonymous": len(spec["users"]) + 1,
                                            "fields": {}, "parent_bundles": [], "child_bundles": []}

    # -- taxonomy (only when the spec declares vocabularies) ------------------
    tid_counter = Counter()
    if spec.get("vocabularies"):
        build_drupal7_taxonomy(spec, schema, expected, tid_counter)

    # -- field config ------------------------------------------------------
    field_config = schema.table(
        "field_config",
        [("id", "int(10) unsigned NOT NULL"), ("field_name", "varchar(32) NOT NULL"), ("type", "varchar(128) NOT NULL"),
         ("module", "varchar(128) NOT NULL DEFAULT ''"), ("active", "tinyint(4) NOT NULL DEFAULT 0"), ("storage_type", "varchar(128) NOT NULL"),
         ("storage_module", "varchar(128) NOT NULL DEFAULT ''"), ("storage_active", "tinyint(4) NOT NULL DEFAULT 0"),
         ("locked", "tinyint(4) NOT NULL DEFAULT 0"), ("data", "longblob NOT NULL"), ("cardinality", "tinyint(4) NOT NULL DEFAULT 0"),
         ("translatable", "tinyint(4) NOT NULL DEFAULT 0"), ("deleted", "tinyint(4) NOT NULL DEFAULT 0")],
        primary_key=["id"],
    )
    field_instance = schema.table(
        "field_config_instance",
        [("id", "int(10) unsigned NOT NULL"), ("field_id", "int(10) unsigned NOT NULL"), ("field_name", "varchar(32) NOT NULL DEFAULT ''"),
         ("entity_type", "varchar(32) NOT NULL DEFAULT ''"), ("bundle", "varchar(128) NOT NULL DEFAULT ''"), ("data", "longblob NOT NULL"),
         ("deleted", "tinyint(4) NOT NULL DEFAULT 0")],
        primary_key=["id"],
    )
    field_ids = {}
    for i, (field_name, fdef) in enumerate(field_defs.items(), start=1):
        ftype = fdef["type"]
        settings = {}
        if ftype == "taxonomy_term_reference":
            settings = {"allowed_values": [{"vocabulary": fdef["vocabulary"], "parent": 0}]}
        elif ftype == "paragraphs":
            settings = {}
        field_config.add(id=i, field_name=field_name, type=ftype, module=D7_FIELD_MODULE[ftype], active=1,
                         storage_type="field_sql_storage", storage_module="field_sql_storage", storage_active=1, locked=0,
                         data=php_serialize({"translatable": 0, "entity_types": [], "settings": settings,
                                             "storage": {"type": "field_sql_storage", "settings": [], "module": "field_sql_storage", "active": 1},
                                             "foreign keys": [], "indexes": [], "id": str(i)}),
                         cardinality=int(fdef.get("cardinality", 1)), translatable=0, deleted=0)
        field_ids[field_name] = i
        cols = d7_field_columns(field_name, ftype)
        schema.table("field_data_" + field_name, cols, primary_key=["entity_type", "entity_id", "deleted", "delta", "language"])
        schema.table("field_revision_" + field_name, cols, primary_key=["entity_type", "entity_id", "revision_id", "deleted", "delta", "language"])
    instance_id = Counter()

    def add_instance(entity_type, bundle, field_name, fdef):
        ftype = field_defs[field_name]["type"]
        inst_settings = {}
        if ftype == "paragraphs":
            inst_settings = {"allowed_bundles": {b: b for b in fdef["children"]}, "bundle_weights": {b: i for i, b in enumerate(fdef["children"])},
                             "title": "Paragraph", "title_multiple": "Paragraphs", "default_edit_mode": "open", "add_mode": "select"}
        elif ftype == "text_with_summary":
            inst_settings = {"text_processing": 1, "display_summary": 1, "user_register_form": False}
        elif ftype in ("text", "text_long"):
            inst_settings = {"text_processing": 0, "user_register_form": False}
        field_instance.add(id=instance_id.next(), field_id=field_ids[field_name], field_name=field_name, entity_type=entity_type,
                           bundle=bundle, deleted=0,
                           data=php_serialize({"label": fdef.get("label", field_name.replace("field_", "").title()),
                                               "widget": {"type": "text_textfield", "weight": 0, "settings": [], "module": "text"},
                                               "settings": inst_settings, "display": {"default": {"label": "above", "type": "text_default"}},
                                               "required": 0, "description": ""}))

    def field_rows(entity_type, bundle, field_name, entity_id, revision_id, delta, values, current):
        row = {"entity_type": entity_type, "bundle": bundle, "deleted": 0, "entity_id": entity_id, "revision_id": revision_id,
               "language": node_language, "delta": delta}
        for suffix, value in values.items():
            row["%s_%s" % (field_name, suffix)] = value
        schema.tables["field_revision_" + field_name].add(**row)
        if current:
            schema.tables["field_data_" + field_name].add(**row)

    # -- paragraphs tables -------------------------------------------------
    para_bundle_table = schema.table(
        "paragraphs_bundle",
        [("bundle", "varchar(32) NOT NULL"), ("name", "varchar(255) NOT NULL"), ("locked", "tinyint(4) NOT NULL DEFAULT 0")],
        primary_key=["bundle"],
    )
    para_item = schema.table(
        "paragraphs_item",
        [("item_id", "int(10) unsigned NOT NULL"), ("revision_id", "int(10) unsigned NOT NULL"), ("field_name", "varchar(32) NOT NULL"),
         ("bundle", "varchar(32) NOT NULL"), ("archived", "tinyint(4) NOT NULL DEFAULT 0")],
        primary_key=["item_id"],
        indexes=[("bundle", ["bundle"]), ("field_name", ["field_name"])],
    )
    para_item_revision = schema.table(
        "paragraphs_item_revision",
        [("revision_id", "int(10) unsigned NOT NULL"), ("item_id", "int(10) unsigned NOT NULL")],
        primary_key=["revision_id"],
    )
    for bundle, bspec in para_bundles.items():
        para_bundle_table.add(bundle=bundle, name=bspec["label"], locked=0)
        for field_name, fdef in bspec["fields"].items():
            add_instance("paragraphs_item", bundle, field_name, fdef)

    item_counter = Counter()
    prid_counter = Counter()
    paragraphs = []  # item_id, rid, bundle, field_name, host_type, host_bundle, host_id, root_nid, attached

    def make_paragraph(bundle, field_name, host_type, host_bundle, host_id, root_nid, attached):
        item_id = item_counter.next()
        rid = prid_counter.next()
        para_item.add(item_id=item_id, revision_id=rid, field_name=field_name, bundle=bundle, archived=0)
        para_item_revision.add(revision_id=rid, item_id=item_id)
        record = {"item_id": item_id, "rid": rid, "bundle": bundle, "field_name": field_name, "host_type": host_type,
                  "host_bundle": host_bundle, "host_id": host_id, "root_nid": root_nid, "attached": attached}
        paragraphs.append(record)
        for child_field, fdef in para_bundles[bundle]["fields"].items():
            if field_defs[child_field]["type"] != "paragraphs":
                continue
            for delta, child_bundle in enumerate(fdef["children"]):
                child = make_paragraph(child_bundle, child_field, "paragraphs_item", bundle, item_id, root_nid, attached)
                field_rows("paragraphs_item", bundle, child_field, item_id, rid, delta,
                           {"value": child["item_id"], "revision_id": child["rid"]}, current=True)
        return record

    # -- nodes -------------------------------------------------------------
    node = schema.table(
        "node",
        [("nid", "int(10) unsigned NOT NULL"), ("vid", "int(10) unsigned DEFAULT NULL"), ("type", "varchar(32) NOT NULL DEFAULT ''"),
         ("language", "varchar(12) NOT NULL DEFAULT ''"), ("title", "varchar(255) NOT NULL DEFAULT ''"), ("uid", "int(11) NOT NULL DEFAULT 0"),
         ("status", "int(11) NOT NULL DEFAULT 1"), ("created", "int(11) NOT NULL DEFAULT 0"), ("changed", "int(11) NOT NULL DEFAULT 0"),
         ("comment", "int(11) NOT NULL DEFAULT 0"), ("promote", "int(11) NOT NULL DEFAULT 0"), ("sticky", "int(11) NOT NULL DEFAULT 0"),
         ("tnid", "int(10) unsigned NOT NULL DEFAULT 0"), ("translate", "int(11) NOT NULL DEFAULT 0")],
        primary_key=["nid"],
        indexes=[("node_type", ["type"]), ("node_status_type", ["status", "type", "nid"])],
    )
    node_revision = schema.table(
        "node_revision",
        [("nid", "int(10) unsigned NOT NULL DEFAULT 0"), ("vid", "int(10) unsigned NOT NULL"), ("uid", "int(11) NOT NULL DEFAULT 0"),
         ("title", "varchar(255) NOT NULL DEFAULT ''"), ("log", "longtext NOT NULL"), ("timestamp", "int(11) NOT NULL DEFAULT 0"),
         ("status", "int(11) NOT NULL DEFAULT 1"), ("comment", "int(11) NOT NULL DEFAULT 0"), ("promote", "int(11) NOT NULL DEFAULT 0"),
         ("sticky", "int(11) NOT NULL DEFAULT 0")],
        primary_key=["vid"],
    )
    node_type = schema.table(
        "node_type",
        [("type", "varchar(32) NOT NULL"), ("name", "varchar(255) NOT NULL DEFAULT ''"), ("base", "varchar(255) NOT NULL"),
         ("module", "varchar(255) NOT NULL"), ("description", "mediumtext NOT NULL"), ("help", "mediumtext NOT NULL"),
         ("has_title", "tinyint(3) unsigned NOT NULL"), ("title_label", "varchar(255) NOT NULL DEFAULT ''"), ("custom", "tinyint(4) NOT NULL DEFAULT 0"),
         ("modified", "tinyint(4) NOT NULL DEFAULT 0"), ("locked", "tinyint(4) NOT NULL DEFAULT 0"), ("disabled", "tinyint(4) NOT NULL DEFAULT 0"),
         ("orig_type", "varchar(255) NOT NULL DEFAULT ''")],
        primary_key=["type"],
    )
    url_alias = schema.table(
        "url_alias",
        [("pid", "int(10) unsigned NOT NULL"), ("source", "varchar(255) NOT NULL DEFAULT ''"), ("alias", "varchar(255) NOT NULL DEFAULT ''"),
         ("language", "varchar(12) NOT NULL DEFAULT ''")],
        primary_key=["pid"],
    )
    nid_counter = Counter()
    vid_counter = Counter()
    pid_counter = Counter()
    nodes = []
    uids = [i for i, u in enumerate(spec["users"], start=1) if u["status"]] or [1]
    for bundle, bspec in node_bundles.items():
        node_type.add(type=bundle, name=bspec["label"], base="node_content", module="node", description="", help="", has_title=1,
                      title_label="Title", custom=1, modified=1, locked=0, disabled=0, orig_type=bundle)
        for field_name, fdef in bspec["fields"].items():
            add_instance("node", bundle, field_name, fdef)
        count = int(bspec["count"])
        revisions = int(bspec.get("revisions", 1))
        unpublished = int(bspec.get("unpublished", 0))
        planned = list(range(nid_counter.value + 1, nid_counter.value + 1 + count))
        para_populated = {f: set(choose_populated(rng, planned, fdef.get("population", 1.0)))
                          for f, fdef in bspec["fields"].items() if field_defs[f]["type"] == "paragraphs"}
        bspec["_para_populated"] = para_populated
        bundle_nids = []
        for i in range(1, count + 1):
            nid = nid_counter.next()
            status = 0 if i > count - unpublished else 1
            title = "%s %d" % (bspec["label"], i)
            vids = [vid_counter.next() for _ in range(revisions)]
            created = epoch + nid * 3600
            uid = uids[(nid - 1) % len(uids)]
            node.add(nid=nid, vid=vids[-1], type=bundle, language=node_language, title=title, uid=uid, status=status,
                     created=created, changed=created + (revisions - 1) * 600, comment=0, promote=1 if bundle == "article" else 0,
                     sticky=0, tnid=0, translate=0)
            for r, vid in enumerate(vids):
                node_revision.add(nid=nid, vid=vid, uid=uid, title=title, log="Revision %d" % (r + 1), timestamp=created + r * 600,
                                  status=status, comment=0, promote=1 if bundle == "article" else 0, sticky=0)
            pid = pid_counter.next()
            alias = "%s/%s" % (bspec["alias_prefix"], slugify(title))
            url_alias.add(pid=pid, source="node/%d" % nid, alias=alias, language=node_language)
            record = {"nid": nid, "bundle": bundle, "status": status, "vids": vids, "title": title, "alias": alias}
            nodes.append(record)
            bundle_nids.append(nid)
            for field_name, fdef in bspec["fields"].items():
                if field_defs[field_name]["type"] != "paragraphs" or nid not in para_populated[field_name]:
                    continue
                children = [make_paragraph(cb, field_name, "node", bundle, nid, nid, True) for cb in fdef["children"]]
                for vid in vids:
                    for delta, child in enumerate(children):
                        field_rows("node", bundle, field_name, nid, vid, delta,
                                   {"value": child["item_id"], "revision_id": child["rid"]}, current=(vid == vids[-1]))
        bspec["_nids"] = bundle_nids

    for bundle, bspec in para_bundles.items():
        for _ in range(int(bspec.get("orphans", 0))):
            host = bspec["orphan_parent"]
            if host["type"] == "node":
                make_paragraph(bundle, host["field"], "node", host["bundle"], node_bundles[host["bundle"]]["_nids"][-1], None, False)
            else:
                parent = [q for q in paragraphs if q["bundle"] == host["bundle"]][-1]
                make_paragraph(bundle, host["field"], "paragraphs_item", host["bundle"], parent["item_id"], None, False)

    # -- leaf values and expectations --------------------------------------
    nodes_by_nid = {n["nid"]: n for n in nodes}
    for bundle, bspec in node_bundles.items():
        nids = bspec["_nids"]
        fields_expected = {}
        for field_name, fdef in bspec["fields"].items():
            ftype = field_defs[field_name]["type"]
            if ftype == "paragraphs":
                populated = sorted(bspec["_para_populated"][field_name])
                fields_expected[field_name] = {"type": ftype, "populated": len(populated), "population_pct": pct(len(populated), len(nids)),
                                               "target_type": "paragraphs_item", "target_bundles": sorted(set(fdef["children"]))}
                continue
            populated = choose_populated(rng, nids, fdef["population"])
            for nid in populated:
                n = nodes_by_nid[nid]
                for vid in n["vids"]:
                    if ftype == "taxonomy_term_reference":
                        field_rows("node", bundle, field_name, nid, vid, 0, {"tid": 1 + (nid % max(tid_counter.value, 1))}, current=(vid == n["vids"][-1]))
                    else:
                        field_rows("node", bundle, field_name, nid, vid, 0, d7_leaf_value(field_name, ftype, n["title"]), current=(vid == n["vids"][-1]))
            fields_expected[field_name] = {"type": ftype, "populated": len(populated), "population_pct": pct(len(populated), len(nids))}
        published = [n for n in nodes if n["bundle"] == bundle and n["status"] == 1]
        expected["entities"]["node"][bundle] = {
            "label": bspec["label"], "distinct": len(nids), "active": len(published), "unpublished": len(nids) - len(published),
            "revisions_per_entity": int(bspec.get("revisions", 1)), "languages": [node_language],
            "node_rows": len(nids), "node_revision_rows": len(nids) * int(bspec.get("revisions", 1)),
            "fields": fields_expected, "parent_bundles": [],
            "child_bundles": sorted({c for f, fd in bspec["fields"].items() if field_defs[f]["type"] == "paragraphs" for c in fd["children"]}),
        }
        expected["content_inventory"]["node"][bundle] = {"total": len(nids), "published": len(published), "languages": {node_language: len(nids)}}
        expected["language_coverage"][bundle] = {node_language: len(nids)}
        first = published[0]
        expected["examples"][bundle] = {"nid": first["nid"], "title": first["title"], "alias": "/" + first["alias"],
                                        "url": "%s/%s" % (base_url, first["alias"])}

    for bundle, bspec in para_bundles.items():
        instances = [p for p in paragraphs if p["bundle"] == bundle]
        ids = [p["item_id"] for p in instances]
        fields_expected = {}
        by_id = {p["item_id"]: p for p in instances}
        for field_name, fdef in bspec["fields"].items():
            ftype = field_defs[field_name]["type"]
            if ftype == "paragraphs":
                fields_expected[field_name] = {"type": ftype, "populated": len(ids), "population_pct": pct(len(ids), len(ids)),
                                               "target_type": "paragraphs_item", "target_bundles": sorted(set(fdef["children"]))}
                continue
            populated = choose_populated(rng, ids, fdef["population"])
            for item_id in populated:
                field_rows("paragraphs_item", bundle, field_name, item_id, by_id[item_id]["rid"], 0,
                           d7_leaf_value(field_name, ftype, "%s %d" % (bspec["label"], item_id)), current=True)
            fields_expected[field_name] = {"type": ftype, "populated": len(populated), "population_pct": pct(len(populated), len(ids))}
        active = [p for p in instances if p["attached"] and p["root_nid"] and nodes_by_nid[p["root_nid"]]["status"] == 1]
        orphans = [p for p in instances if not p["attached"]]
        parent_bundles = []
        for p in instances:
            pb = {"parent_type": p["host_type"], "parent_bundle": p["host_bundle"], "field": p["field_name"]}
            if pb not in parent_bundles:
                parent_bundles.append(pb)
        parent_bundles.sort(key=lambda d: (d["parent_type"], d["parent_bundle"], d["field"]))
        children = sorted({c for f, fd in bspec["fields"].items() if field_defs[f]["type"] == "paragraphs" for c in fd["children"]})
        active_children = [c for c in paragraphs if c["host_type"] == "paragraphs_item" and c["host_id"] in set(ids)
                           and c["attached"] and c["root_nid"] and nodes_by_nid[c["root_nid"]]["status"] == 1]
        expected["entities"]["paragraph"][bundle] = {
            "label": bspec["label"], "distinct": len(ids), "attached": len(ids) - len(orphans), "active": len(active),
            "inactive": len(ids) - len(active), "active_children": len(active_children) if children else 0,
            "orphans": len(orphans), "is_container": bool(children), "fields": fields_expected, "parent_bundles": parent_bundles,
            "root_node_bundles": sorted({nodes_by_nid[p["root_nid"]]["bundle"] for p in instances if p["root_nid"]}),
            "child_bundles": children,
        }

    expected["fields"] = {name: {"type": fdef["type"], "module": D7_FIELD_MODULE[fdef["type"]]} for name, fdef in field_defs.items()}
    expected["url_aliases"] = {"count": len(url_alias.rows), "table": "url_alias"}

    # -- menus (only when the spec declares them) ----------------------------
    menus_expected = {}
    if spec.get("menus"):
        menus_expected = build_drupal7_menus(spec, schema)
    expected["menus"] = menus_expected

    expected["integrations"] = []
    expected["integration_count"] = 0
    expected["tables"] = sorted(schema.tables)
    expected["signature"] = {"present": ["field_config_instance", "node"], "absent": ["config", "key_value", "node_field_data"]}
    for bspec in node_bundles.values():
        bspec.pop("_nids", None)
        bspec.pop("_para_populated", None)
    verify_population(schema, expected, prefixes={"node": "field_data_", "paragraph": "field_data_"})
    return schema, expected


# ---------------------------------------------------------------------------
# WordPress builder
# ---------------------------------------------------------------------------

def build_wordpress(spec, rng):
    schema = Schema()
    epoch = int(spec["epoch"])
    source = spec["source"]
    prefix = spec["prefix"]
    base_url = source["base_url"]
    default_lang = source["default_langcode"]
    site = spec["site"]

    def t(name):
        return prefix + name

    def dt(ts):
        # fixed-epoch wall clock, no time zone dependence
        import datetime
        return datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=ts)

    def stamp(ts):
        return dt(ts).strftime("%Y-%m-%d %H:%M:%S")

    expected = {
        "fixture": spec["name"],
        "kind": spec["kind"],
        "generator_version": GENERATOR_VERSION,
        "source": {
            "technology": source["technology"], "topology": source["topology"], "delivery": source["delivery"],
            "table_prefix": prefix, "db_key": "", "database": spec["database"], "base_url": base_url,
            "default_langcode": default_lang, "languages": list(source["languages"]),
            "multisite_tables_present": False,
        },
        "plugins": {}, "post_types": {}, "content_inventory": {"posts": {}}, "language_coverage": {},
        "examples": {}, "menus": {}, "options": {},
    }

    posts = schema.table(
        t("posts"),
        [("ID", "bigint(20) unsigned NOT NULL"), ("post_author", "bigint(20) unsigned NOT NULL DEFAULT 0"), ("post_date", "datetime NOT NULL"),
         ("post_date_gmt", "datetime NOT NULL"), ("post_content", "longtext NOT NULL"), ("post_title", "text NOT NULL"),
         ("post_excerpt", "text NOT NULL"), ("post_status", "varchar(20) NOT NULL DEFAULT 'publish'"), ("comment_status", "varchar(20) NOT NULL DEFAULT 'open'"),
         ("ping_status", "varchar(20) NOT NULL DEFAULT 'open'"), ("post_password", "varchar(255) NOT NULL DEFAULT ''"), ("post_name", "varchar(200) NOT NULL DEFAULT ''"),
         ("to_ping", "text NOT NULL"), ("pinged", "text NOT NULL"), ("post_modified", "datetime NOT NULL"), ("post_modified_gmt", "datetime NOT NULL"),
         ("post_content_filtered", "longtext NOT NULL"), ("post_parent", "bigint(20) unsigned NOT NULL DEFAULT 0"), ("guid", "varchar(255) NOT NULL DEFAULT ''"),
         ("menu_order", "int(11) NOT NULL DEFAULT 0"), ("post_type", "varchar(20) NOT NULL DEFAULT 'post'"), ("post_mime_type", "varchar(100) NOT NULL DEFAULT ''"),
         ("comment_count", "bigint(20) NOT NULL DEFAULT 0")],
        primary_key=["ID"],
        indexes=[("type_status_date", ["post_type", "post_status", "post_date", "ID"]), ("post_parent", ["post_parent"]), ("post_author", ["post_author"])],
    )
    postmeta = schema.table(
        t("postmeta"),
        [("meta_id", "bigint(20) unsigned NOT NULL"), ("post_id", "bigint(20) unsigned NOT NULL DEFAULT 0"),
         ("meta_key", "varchar(255) DEFAULT NULL"), ("meta_value", "longtext DEFAULT NULL")],
        primary_key=["meta_id"],
        indexes=[("post_id", ["post_id"]), ("meta_key", ["meta_key"])],
    )
    options = schema.table(
        t("options"),
        [("option_id", "bigint(20) unsigned NOT NULL"), ("option_name", "varchar(191) NOT NULL DEFAULT ''"),
         ("option_value", "longtext NOT NULL"), ("autoload", "varchar(20) NOT NULL DEFAULT 'yes'")],
        primary_key=["option_id"],
        indexes=[("option_name", ["option_name"])],
    )
    users = schema.table(
        t("users"),
        [("ID", "bigint(20) unsigned NOT NULL"), ("user_login", "varchar(60) NOT NULL DEFAULT ''"), ("user_pass", "varchar(255) NOT NULL DEFAULT ''"),
         ("user_nicename", "varchar(50) NOT NULL DEFAULT ''"), ("user_email", "varchar(100) NOT NULL DEFAULT ''"), ("user_url", "varchar(100) NOT NULL DEFAULT ''"),
         ("user_registered", "datetime NOT NULL"), ("user_activation_key", "varchar(255) NOT NULL DEFAULT ''"),
         ("user_status", "int(11) NOT NULL DEFAULT 0"), ("display_name", "varchar(250) NOT NULL DEFAULT ''")],
        primary_key=["ID"],
    )
    usermeta = schema.table(
        t("usermeta"),
        [("umeta_id", "bigint(20) unsigned NOT NULL"), ("user_id", "bigint(20) unsigned NOT NULL DEFAULT 0"),
         ("meta_key", "varchar(255) DEFAULT NULL"), ("meta_value", "longtext DEFAULT NULL")],
        primary_key=["umeta_id"],
    )
    terms = schema.table(
        t("terms"),
        [("term_id", "bigint(20) unsigned NOT NULL"), ("name", "varchar(200) NOT NULL DEFAULT ''"), ("slug", "varchar(200) NOT NULL DEFAULT ''"),
         ("term_group", "bigint(10) NOT NULL DEFAULT 0")],
        primary_key=["term_id"],
    )
    term_taxonomy = schema.table(
        t("term_taxonomy"),
        [("term_taxonomy_id", "bigint(20) unsigned NOT NULL"), ("term_id", "bigint(20) unsigned NOT NULL DEFAULT 0"),
         ("taxonomy", "varchar(32) NOT NULL DEFAULT ''"), ("description", "longtext NOT NULL"), ("parent", "bigint(20) unsigned NOT NULL DEFAULT 0"),
         ("count", "bigint(20) NOT NULL DEFAULT 0")],
        primary_key=["term_taxonomy_id"],
    )
    term_rel = schema.table(
        t("term_relationships"),
        [("object_id", "bigint(20) unsigned NOT NULL DEFAULT 0"), ("term_taxonomy_id", "bigint(20) unsigned NOT NULL DEFAULT 0"),
         ("term_order", "int(11) NOT NULL DEFAULT 0")],
        primary_key=["object_id", "term_taxonomy_id"],
    )
    icl = schema.table(
        t("icl_translations"),
        [("translation_id", "bigint(20) NOT NULL"), ("element_type", "varchar(60) NOT NULL DEFAULT 'post_post'"),
         ("element_id", "bigint(20) DEFAULT NULL"), ("trid", "bigint(20) NOT NULL"), ("language_code", "varchar(7) NOT NULL"),
         ("source_language_code", "varchar(7) DEFAULT NULL")],
        primary_key=["translation_id"],
        indexes=[("trid_lang", ["trid", "language_code"]), ("el_type_id", ["element_type", "element_id"])],
    )

    # users
    for i, u in enumerate(spec["users"], start=1):
        users.add(ID=i, user_login=u["login"], user_pass="$P$fixture-hash-not-a-real-password", user_nicename=u["login"],
                  user_email=u["email"], user_url="", user_registered=stamp(epoch + i * 60), user_activation_key="",
                  user_status=0, display_name=u["login"].title())
        usermeta.add(umeta_id=i, user_id=i, meta_key=prefix + "capabilities",
                     meta_value=php_serialize({u.get("role", "author"): True}))
    expected["users"] = {"count": len(spec["users"])}

    # options
    plugins = spec["plugins"]
    active = [p["file"] for p in plugins if p.get("active", True)]
    opt_rows = [
        ("siteurl", base_url), ("home", base_url), ("blogname", site["blogname"]), ("blogdescription", site.get("blogdescription", "")),
        ("admin_email", site["admin_email"]), ("db_version", str(site["db_version"])), ("permalink_structure", site["permalink_structure"]),
        ("template", site["theme"]), ("stylesheet", site["theme"]), ("WPLANG", site.get("wplang", "")),
        ("active_plugins", php_serialize(active)),
        ("posts_per_page", "10"), ("page_on_front", "0"), ("show_on_front", "posts"),
        ("icl_sitepress_settings", php_serialize({"default_language": default_lang, "active_languages": list(source["languages"]),
                                                  "language_negotiation_type": 1, "setup_complete": 1})),
    ]
    for i, (name, value) in enumerate(opt_rows, start=1):
        options.add(option_id=i, option_name=name, option_value=value, autoload="yes")
    expected["plugins"] = {"source": "%soptions.active_plugins" % prefix, "active": sorted(active), "count": len(active),
                           "wpml_active": any("sitepress" in a for a in active),
                           "names": {p["file"]: p["name"] for p in plugins}}
    expected["options"] = {"siteurl": base_url, "permalink_structure": site["permalink_structure"], "theme": site["theme"],
                           "db_version": str(site["db_version"])}

    # terms
    term_id = Counter()
    tt_id = Counter()
    tt_by_slug = {}
    for tax, names in spec["terms"].items():
        for name in names:
            tid = term_id.next()
            ttid = tt_id.next()
            terms.add(term_id=tid, name=name, slug=slugify(name), term_group=0)
            term_taxonomy.add(term_taxonomy_id=ttid, term_id=tid, taxonomy=tax, description="", parent=0, count=0)
            tt_by_slug[(tax, slugify(name))] = ttid
    expected["terms"] = {tax: len(names) for tax, names in spec["terms"].items()}

    # posts
    post_id = Counter()
    meta_id = Counter()
    trid = Counter()
    icl_id = Counter()
    inventory = {}
    by_type_status = {}
    lang_rows = {}
    examples = {}
    uids = list(range(1, len(spec["users"]) + 1)) or [1]

    def add_post(ptype, status, title, parent=0, slug=None, author=None, menu_order=0, content=None):
        pid = post_id.next()
        created = epoch + pid * 3600
        posts.add(ID=pid, post_author=author or uids[(pid - 1) % len(uids)], post_date=stamp(created), post_date_gmt=stamp(created),
                  post_content=content if content is not None else "<p>Content of %s.</p>" % title, post_title=title, post_excerpt="",
                  post_status=status, comment_status="closed", ping_status="closed", post_password="",
                  post_name=slug if slug is not None else slugify(title), to_ping="", pinged="", post_modified=stamp(created + 600),
                  post_modified_gmt=stamp(created + 600), post_content_filtered="", post_parent=parent,
                  guid="%s/?p=%d" % (base_url, pid), menu_order=menu_order, post_type=ptype, post_mime_type="", comment_count=0)
        by_type_status[(ptype, status)] = by_type_status.get((ptype, status), 0) + 1
        return pid

    def add_meta(pid, key, value):
        postmeta.add(meta_id=meta_id.next(), post_id=pid, meta_key=key, meta_value=value)

    def add_translation(element_type, element_id, lang, source_lang, shared_trid):
        icl.add(translation_id=icl_id.next(), element_type=element_type, element_id=element_id, trid=shared_trid,
                language_code=lang, source_language_code=source_lang)
        lang_rows[lang] = lang_rows.get(lang, 0) + 1

    for ptype, tspec in spec["post_types"].items():
        label = tspec["label"]
        publish = int(tspec.get("publish", 0))
        draft = int(tspec.get("draft", 0))
        revisions = int(tspec.get("revisions", 0))
        translations = tspec.get("translations", {})
        published_ids = []
        all_ids = []
        for i in range(1, publish + draft + 1):
            status = "publish" if i <= publish else "draft"
            pid = add_post(ptype, status, "%s %d" % (label, i))
            all_ids.append(pid)
            if status == "publish":
                published_ids.append(pid)
            shared = trid.next()
            add_translation("post_%s" % ptype, pid, default_lang, None, shared)
            for lang, n in translations.items():
                if i <= int(n):
                    tpid = add_post(ptype, status, "%s %d (%s)" % (label, i, lang), slug="%s-%d-%s" % (slugify(label), i, lang))
                    all_ids.append(tpid)
                    if status == "publish":
                        published_ids.append(tpid)
                    add_translation("post_%s" % ptype, tpid, lang, default_lang, shared)
            if tspec.get("categories"):
                cat = tspec["categories"][(i - 1) % len(tspec["categories"])]
                term_rel.add(object_id=pid, term_taxonomy_id=tt_by_slug[("category", slugify(cat))], term_order=0)
            if tspec.get("acf"):
                for f in tspec["acf"]["fields"]:
                    add_meta(pid, f["name"], f["sample"] % i if "%" in str(f["sample"]) else f["sample"])
                    add_meta(pid, "_" + f["name"], f["key"])
        revision_ids = []
        for r in range(revisions):
            target = published_ids[r % len(published_ids)]
            rid = add_post("revision", "inherit", "%s %d" % (label, r + 1), parent=target, slug="%d-revision-v1" % target)
            revision_ids.append(rid)
        translated_count = sum(int(n) for n in translations.values())
        inventory[ptype] = {
            "label": label, "publish": by_type_status.get((ptype, "publish"), 0), "draft": by_type_status.get((ptype, "draft"), 0),
            "total_rows": by_type_status.get((ptype, "publish"), 0) + by_type_status.get((ptype, "draft"), 0),
            "originals": publish + draft, "translations": {lang: int(n) for lang, n in translations.items()},
            "revision_rows": revisions, "rows_including_revisions": by_type_status.get((ptype, "publish"), 0) + by_type_status.get((ptype, "draft"), 0) + revisions,
            "custom_post_type": bool(tspec.get("custom", False)),
        }
        if tspec.get("acf"):
            inventory[ptype]["acf"] = {"group": tspec["acf"]["group"], "fields": [f["name"] for f in tspec["acf"]["fields"]]}
        first = all_ids[0]
        first_row = next(r for r in posts.rows if r["ID"] == first)
        examples[ptype] = {"ID": first, "title": first_row["post_title"], "slug": first_row["post_name"],
                           "url": "%s/%s/" % (base_url, first_row["post_name"])}

    # ACF field group definitions live in posts too
    for ptype, tspec in spec["post_types"].items():
        if not tspec.get("acf"):
            continue
        gid = add_post("acf-field-group", "publish", tspec["acf"]["group"], slug="group_%s" % ptype,
                       content=php_serialize({"location": [[{"param": "post_type", "operator": "==", "value": ptype}]], "active": 1}))
        for i, f in enumerate(tspec["acf"]["fields"]):
            add_post("acf-field", "publish", f["name"].title(), parent=gid, slug=f["key"], menu_order=i,
                     content=php_serialize({"type": f["type"], "name": f["name"], "required": 0}))

    # menus: nav_menu term + nav_menu_item posts
    menus_expected = {}
    for menu_name, items in spec["menus"].items():
        tid = term_id.next()
        ttid = tt_id.next()
        terms.add(term_id=tid, name=menu_name.title(), slug=slugify(menu_name), term_group=0)
        term_taxonomy.add(term_taxonomy_id=ttid, term_id=tid, taxonomy="nav_menu", description="", parent=0, count=len(items))
        item_ids = {}
        for order, item in enumerate(items, start=1):
            pid = add_post("nav_menu_item", "publish", item["title"], slug=str(0), menu_order=order, content="")
            posts.rows[-1]["post_name"] = str(pid)
            item_ids[item["title"]] = pid
            term_rel.add(object_id=pid, term_taxonomy_id=ttid, term_order=0)
            if "url" in item:
                add_meta(pid, "_menu_item_type", "custom")
                add_meta(pid, "_menu_item_object", "custom")
                add_meta(pid, "_menu_item_object_id", str(pid))
                add_meta(pid, "_menu_item_url", item["url"])
            else:
                target_type = item["post_type"]
                target = examples[target_type]["ID"] + int(item.get("index", 0))
                add_meta(pid, "_menu_item_type", "post_type")
                add_meta(pid, "_menu_item_object", target_type)
                add_meta(pid, "_menu_item_object_id", str(target))
            add_meta(pid, "_menu_item_menu_item_parent", str(item_ids.get(item.get("parent"), 0)))
        menus_expected[menu_name] = {"items": len(items), "top_level": sum(1 for i in items if not i.get("parent"))}
    expected["menus"] = menus_expected

    expected["post_types"] = inventory
    expected["content_inventory"]["posts"] = {"%s/%s" % k: v for k, v in sorted(by_type_status.items())}
    expected["language_coverage"] = {"source": "%sicl_translations" % prefix, "rows_by_language": dict(sorted(lang_rows.items()))}
    expected["examples"] = examples
    expected["tables"] = sorted(schema.tables)
    expected["signature"] = {"present": [t("posts"), t("options"), t("postmeta")], "absent": [t("blogs"), t("site"), t("sitemeta")]}
    return schema, expected


# ---------------------------------------------------------------------------
# Unknown-CMS builder
# ---------------------------------------------------------------------------

def build_unknown(spec, rng):
    schema = Schema()
    epoch = int(spec["epoch"])
    source = spec["source"]
    pages = schema.table(
        "cms_pages",
        [("id", "int(10) unsigned NOT NULL"), ("slug", "varchar(190) NOT NULL"), ("title", "varchar(255) NOT NULL"),
         ("body", "longtext DEFAULT NULL"), ("published", "tinyint(1) NOT NULL DEFAULT 0"), ("author_id", "int(10) unsigned DEFAULT NULL"),
         ("created_at", "int(11) NOT NULL")],
        primary_key=["id"],
    )
    cms_users = schema.table(
        "cms_users",
        [("id", "int(10) unsigned NOT NULL"), ("username", "varchar(60) NOT NULL"), ("email", "varchar(190) NOT NULL"),
         ("is_admin", "tinyint(1) NOT NULL DEFAULT 0"), ("created_at", "int(11) NOT NULL")],
        primary_key=["id"],
    )
    for i, u in enumerate(spec["users"], start=1):
        cms_users.add(id=i, username=u["username"], email=u["email"], is_admin=int(u.get("is_admin", False)), created_at=epoch + i * 60)
    published = 0
    for i in range(1, int(spec["pages"]["count"]) + 1):
        is_pub = i <= int(spec["pages"]["published"])
        published += int(is_pub)
        pages.add(id=i, slug="page-%d" % i, title="Page %d" % i, body="<p>Body of page %d.</p>" % i, published=int(is_pub),
                  author_id=1 + (i % len(spec["users"])), created_at=epoch + i * 3600)
    expected = {
        "fixture": spec["name"], "kind": spec["kind"], "generator_version": GENERATOR_VERSION,
        "source": {"technology": "other", "topology": "unknown", "delivery": source["delivery"], "db_key": spec["database"],
                   "database": spec["database"], "table_prefix": "", "base_url": source["base_url"],
                   "default_langcode": source["default_langcode"], "languages": list(source["languages"]),
                   "expected_behaviour": "stop and ask the user to confirm the source system"},
        "tables": sorted(schema.tables),
        "signature": {"present": [], "absent": ["config", "key_value", "field_config_instance", "node", "wp_posts", "wp_options", "wp_postmeta", "wp_blogs"]},
        "content_inventory": {"cms_pages": {"total": int(spec["pages"]["count"]), "published": published}},
        "users": {"count": len(spec["users"])},
    }
    return schema, expected


BUILDERS = {"drupal8": build_drupal8, "drupal7": build_drupal7, "wordpress": build_wordpress, "unknown": build_unknown}


# ---------------------------------------------------------------------------
# Domain scan: fixtures hold no real hosts
# ---------------------------------------------------------------------------

HOST_RE = re.compile(r"(?:https?://|@)([A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,})(?=[/:?#'\"\s;,)]|$)")


def host_allowed(host):
    host = host.lower().rstrip(".")
    return host == "example.com" or host.endswith(".example.com") or host.endswith(".example")


def scan_domains(text):
    """Return the sorted set of hosts in URLs or e-mail addresses that are not documentation domains."""
    return sorted({h for h in HOST_RE.findall(text) if not host_allowed(h)})


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
    outputs = {"dump.sql": dump, "expected.json": expected_text}
    bad = {f: scan_domains(text) for f, text in outputs.items()}
    bad = {f: hosts for f, hosts in bad.items() if hosts}
    if bad:
        for f, hosts in bad.items():
            print("%s/%s: host(s) outside .example / example.com: %s" % (name, f, ", ".join(hosts)))
        raise SystemExit("%s: fixtures must use reserved documentation domains only; fix spec.json" % name)
    return outputs


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
        hosts = scan_domains(committed)
        if hosts:
            print("%s/%s: host(s) outside .example / example.com: %s" % (name, filename, ", ".join(hosts)))
            ok = False
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
