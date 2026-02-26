#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import time
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import requests

import os

import re
import sys
from pathlib import Path

import fitz # PyMuPDF
from PIL import Image


DEFAULT_DETAIL_TEMPLATE = "https://ereserves.lib.tsinghua.edu.cn/bookDetail/{book_id}"
DEFAULT_CLICK_SELECTOR = (
    "#app > div > div.main-body > div > div.booksDetail_lft > div.flex_cc_row > "
    "div.booksDetail_right > div.booksBtn > div:nth-child(1) > button"
)
DEFAULT_CHAPTERS_API = (
    "https://ereserves.lib.tsinghua.edu.cn/readkernel/KernelAPI/BookInfo/selectJgpBookChapters"
)
DEFAULT_CHAPTER_API = (
    "https://ereserves.lib.tsinghua.edu.cn/readkernel/KernelAPI/BookInfo/selectJgpBookChapter"
)
DEFAULT_ENTRY_URL = "https://ereserves.lib.tsinghua.edu.cn/"
DEFAULT_TIMEOUT_MS = 45000
DEFAULT_SCAN_TIMEOUT_MS = 90000
DEFAULT_ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9"

EXPORT_DPI = 144.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Open bookDetail page, click the read button to navigate to the viewer page, "
            "extract input#scanid value, then call chapter APIs and download JPGs."
        )
    )
    parser.add_argument("detailnumber", help="bookDetailNumber (e.g. the number in /bookDetail/<detailnumber>)")
    return parser.parse_args()


def _origin_for_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return "https://ereserves.lib.tsinghua.edu.cn"
    return f"{parsed.scheme}://{parsed.netloc}"


def _last_path_segment(url: str) -> str:
    parsed = urlparse(url)
    path = (parsed.path or "").rstrip("/")
    if not path:
        return ""
    return path.split("/")[-1]


def _get_cookie_value(context, url: str, cookie_name: str) -> Optional[str]:
    try:
        cookies = context.cookies(url)
    except Exception:
        cookies = []

    for c in cookies:
        if c.get("name") == cookie_name and c.get("value"):
            return str(c["value"])

    lowered = cookie_name.lower()
    for c in cookies:
        if str(c.get("name", "")).lower() == lowered and c.get("value"):
            return str(c["value"])

    return None


def _post_form_json(
    context,
    api_url: str,
    form: Dict[str, str],
    referer: str,
    accept_language: str,
) -> dict:
    botu_read_kernel = _get_cookie_value(context, api_url, "BotuReadKernel")
    if not botu_read_kernel:
        raise SystemExit(
            "ERROR: missing cookie BotuReadKernel in this browser context. "
            "Make sure you successfully opened the viewer page via the button click before calling the API."
        )

    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": accept_language,
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": _origin_for_url(referer),
        "referer": referer,
        "x-requested-with": "XMLHttpRequest",
        "botureadkernel": botu_read_kernel,
    }

    resp = context.request.post(api_url, headers=headers, form=form)
    text = resp.text()
    if resp.status < 200 or resp.status >= 300:
        snippet = text[:500].strip().replace("\n", " ")
        raise SystemExit(f"ERROR: API HTTP {resp.status}. url={api_url} Body: {snippet}")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        snippet = text[:500].strip().replace("\n", " ")
        raise SystemExit(f"ERROR: API did not return JSON. url={api_url} Body: {snippet}")


def _extract_scanid_now(page) -> Optional[str]:
    selectors = [
        "input#scanid",
        'input[id="scanid" i]',
        "#scanid",
        '[id="scanid" i]',
        'input[name="scanid" i]',
    ]

    for frame in page.frames:
        for sel in selectors:
            loc = frame.locator(sel).first
            try:
                if loc.count() == 0:
                    continue
            except Exception:
                continue

            for getter in (
                lambda: loc.get_attribute("value"),
                lambda: loc.input_value(timeout=500),
                lambda: loc.evaluate("el => el.value"),
            ):
                try:
                    value = getter()
                except Exception:
                    continue
                if value and str(value).strip():
                    return str(value).strip()

    return None


def _new_pages_since(context_pages: Sequence, before: Sequence) -> List:
    before_ids = {id(p) for p in before}
    return [p for p in context_pages if id(p) not in before_ids]


def _wait_for_scanid(pages: Sequence, timeout_ms: int) -> Tuple[str, str]:
    deadline = time.time() + (timeout_ms / 1000.0)
    last_urls: Dict[int, str] = {}

    while time.time() < deadline:
        for p in pages:
            try:
                last_urls[id(p)] = p.url
            except Exception:
                pass
            scanid = _extract_scanid_now(p)
            if scanid:
                try:
                    return scanid, p.url
                except Exception:
                    return scanid, ""
        time.sleep(0.2)

    urls = ", ".join(sorted({u for u in last_urls.values() if u}))
    raise SystemExit(f"ERROR: scanid not found within timeout. seen_urls=[{urls}]")


def main() -> None:
    args = parse_args()

    doc = fitz.open()
    toc: list[list[int | str]] = []
    page_index = 0  # 0-based, but toc uses 1-based page numbers

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        page.goto(DEFAULT_ENTRY_URL, wait_until="domcontentloaded")
        print(
            "已打开登录页面，请在弹出的浏览器里完成登录。\n"
            "确认你已经登录成功后，回到终端按回车继续…"
        )
        input()

        book_id = args.detailnumber
        book_id_encoded = quote(str(book_id), safe="")
        detail_url = DEFAULT_DETAIL_TEMPLATE.format(book_id=book_id_encoded)

        page.goto(detail_url, wait_until="domcontentloaded")
        button = page.locator(DEFAULT_CLICK_SELECTOR).first
        button.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)

        before_pages = list(context.pages)
        button.click()

        deadline = time.time() + (DEFAULT_SCAN_TIMEOUT_MS / 1000.0)
        candidate_pages: Sequence = [page]
        scanid: Optional[str] = None
        found_url: str = ""

        while time.time() < deadline:
            new_pages = _new_pages_since(context.pages, before_pages)
            if new_pages:
                candidate_pages = list(dict.fromkeys([new_pages[-1], page] + new_pages))
                break

            maybe_scanid = _extract_scanid_now(page)
            if maybe_scanid:
                candidate_pages = []
                scanid = maybe_scanid
                found_url = str(page.url or "")
                break

            time.sleep(0.2)

        if candidate_pages:
            remaining_ms = max(0, int((deadline - time.time()) * 1000))
            scanid, found_url = _wait_for_scanid(candidate_pages, timeout_ms=remaining_ms)
        else:
            if not scanid:
                raise SystemExit("ERROR: scanid not found")

        viewer_bookid = _last_path_segment(found_url)
        if not viewer_bookid:
            raise SystemExit(f"ERROR: cannot extract viewer bookid from url: {found_url}")

        chapters = _post_form_json(
            context=context,
            api_url=DEFAULT_CHAPTERS_API,
            form={"SCANID": scanid},
            referer=found_url or detail_url,
            accept_language=DEFAULT_ACCEPT_LANGUAGE,
        )
        data = chapters.get("data")
        if not isinstance(data, list):
            raise SystemExit("ERROR: chapters JSON missing list field: data")

        cookies = context.cookies()
        s = requests.Session()
        for c in cookies:
            s.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path"))

        img_api_url = "https://ereserves.lib.tsinghua.edu.cn/readkernel/JPGFile/DownJPGJsNetPage"
        for item in data:
            if not isinstance(item, dict):
                continue
            emid = item.get("EMID") or item.get("emid")
            if not emid:
                continue

            detail = _post_form_json(
                context=context,
                api_url=DEFAULT_CHAPTER_API,
                form={"EMID": str(emid), "BOOKID": viewer_bookid},
                referer=found_url or detail_url,
                accept_language=DEFAULT_ACCEPT_LANGUAGE,
            )

            chapter_name = item.get("EFRAGMENTNAME") or str(emid)
            toc.append([1, chapter_name, page_index + 1])
            print(chapter_name)
            os.makedirs(f"downloads/{book_id}/{chapter_name}", exist_ok=True)

            detail_data = detail.get("data") if isinstance(detail, dict) else None
            jgps = detail_data.get("JGPS") if isinstance(detail_data, dict) else None
            if not isinstance(jgps, list):
                continue

            for img in jgps:
                if not isinstance(img, dict):
                    continue
                hfs_key = img.get("hfsKey")
                if not hfs_key:
                    continue
                print(hfs_key)
                out_name = str(hfs_key).rsplit("/", 1)[-1] or "page.jpg"
                r = s.get(
                    img_api_url,
                    params={"filePath": hfs_key},
                    headers={"Referer": found_url},
                    stream=True,
                    timeout=30,
                )
                r.raise_for_status()

                with open(f"downloads/{book_id}/{chapter_name}/{out_name}", "wb") as f:
                    for chunk in r.iter_content(8192):
                        if chunk:
                            f.write(chunk)

                with Image.open(f"downloads/{book_id}/{chapter_name}/{out_name}") as im:
                    width_px, height_px = im.size
                    width_pt = width_px * 72.0 / EXPORT_DPI
                    height_pt = height_px * 72.0 / EXPORT_DPI
                    doc_page = doc.new_page(width=width_pt, height=height_pt)
                    doc_page.insert_image(doc_page.rect, filename=str(f"downloads/{book_id}/{chapter_name}/{out_name}"), keep_proportion=True)
                    page_index += 1

        for p2 in context.pages:
            if p2 is page:
                continue
            try:
                p2.close()
            except Exception:
                pass

        context.close()
        browser.close()

        doc.set_toc(toc)
        os.makedirs("output", exist_ok=True)
        output_pdf = Path(f"output/{quote(str(args.detailnumber),safe='')}.pdf")
        doc.save(str(output_pdf), deflate=True, garbage=4)



if __name__ == "__main__":
    try:
        main()
    except PlaywrightTimeoutError as e:
        raise SystemExit(f"ERROR: playwright timeout: {e}") from e
