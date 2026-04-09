#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re


def apply_regex_rules(file_path, regex_pattern=None, regex_replace=None):
    if not regex_pattern:
        return True, file_path

    try:
        match = re.search(regex_pattern, file_path)
        if not match:
            return False, file_path

        if regex_replace and regex_replace.strip():
            new_path = re.sub(regex_pattern, regex_replace, file_path)
            if new_path != file_path:
                return True, new_path

        return True, file_path
    except re.error:
        return True, file_path
    except Exception:
        return True, file_path


def should_include_folder(folder_name, folder_filter=None):
    if not folder_filter:
        return True

    try:
        if isinstance(folder_filter, list):
            for pattern in folder_filter:
                if re.search(pattern, folder_name):
                    return True
            return False

        if isinstance(folder_filter, str):
            return bool(re.search(folder_filter, folder_name))

        return True
    except re.error:
        return True
    except Exception:
        return True


def extract_file_info(file_dict):
    try:
        if isinstance(file_dict, dict):
            server_filename = file_dict.get("server_filename", "")
            if not server_filename and file_dict.get("path"):
                server_filename = file_dict["path"].split("/")[-1]

            return {
                "server_filename": server_filename,
                "fs_id": file_dict.get("fs_id", ""),
                "path": file_dict.get("path", ""),
                "size": file_dict.get("size", 0),
                "isdir": file_dict.get("isdir", 0),
                "md5": file_dict.get("md5", None),
            }
        return None
    except Exception:
        return None
