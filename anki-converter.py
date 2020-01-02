#!/usr/bin/env python

import json
import sys
import sqlite3
import re
import shutil
import inflect
import string
from operator import itemgetter
from PIL import Image
from pathlib import Path
from html.parser import HTMLParser
from typing import Dict, List, TextIO


NUM_WORDS_TO_KEEP = 4

CELL_WIDTH = 109
CELL_HEIGHT = 109
NUM_CELLS_PER_LINE = 10
IMAGE_BACKGROUND_COLOR = (255, 255, 255)

INPUT_DIR = Path('/Users/phil/dev/Nihongo/media/sources/kanji/Heisigs_RTK_6th_Edition-_Stories_Stroke_diagrams_Readings/')
DB_FILE = INPUT_DIR / 'collection.anki2'
MEDIA_FILE = INPUT_DIR / 'media'
OUTPUT_FILE = Path('kanji.csv')
MEDIA_PREFIX = 'stroke-order/kanji/'
MEDIA_OUTPUT_DIR = Path('/Users/phil/dev/Nihongo/media/stroke-order/kanji')

db = sqlite3.connect(str(DB_FILE))


def process_stroke(src_path: Path, dst_path: Path):
    img = Image.open(str(src_path))
    width, height = img.size
    assert height == CELL_HEIGHT
    ncols = int(width / CELL_WIDTH)
    if ncols > NUM_CELLS_PER_LINE:
        new_width = NUM_CELLS_PER_LINE * CELL_WIDTH
        new_height = (int(ncols / NUM_CELLS_PER_LINE) + 1) * CELL_HEIGHT
        new_img = Image.new(mode="RGB", size=(new_width, new_height))
        new_img.paste(IMAGE_BACKGROUND_COLOR, box=(0, 0, new_width, new_height))

        for i in range(ncols):
            src_pos = (i * CELL_WIDTH, 0)
            src_box = (*src_pos, src_pos[0] + CELL_WIDTH, src_pos[1] + CELL_HEIGHT)
            row = int(i / NUM_CELLS_PER_LINE)
            col = i % NUM_CELLS_PER_LINE
            dst_pos = (col * CELL_WIDTH, row * CELL_HEIGHT)
            dst_box = (*dst_pos, dst_pos[0] + CELL_WIDTH, dst_pos[1] + CELL_HEIGHT)
            reg = img.crop(src_box)
            new_img.paste(reg, dst_box)
        new_img.save(str(dst_path))
    else:
        shutil.copyfile(src=str(src_path), dst=str(dst_path))


def get_media_mapping() -> Dict[str, str]:
    media_json = None
    with open(str(MEDIA_FILE)) as fp:
        media_json = json.load(fp)
    return media_json


def get_fields() -> List[str]:
    cur = db.cursor()
    cur.execute("select models from col")
    rows = cur.fetchall()
    assert len(rows) > 0
    models_json = rows[0][0]
    models = json.loads(models_json)
    assert len(models) > 0
    model = list(models.values())[0]
    fields = model['flds']
    return [x['name'] for x in fields]


# From: https://stackoverflow.com/questions/11061058/using-htmlparser-in-python-3-2
class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def get_data(self):
        return ''.join(self.fed)


def write_row(fp: TextIO, row: List[str]):
    fp.write(', '.join(row) + '\n')


def write_kanji(fp: TextIO, field_names: List[str], field_map: Dict[str, str]):
    words = field_map['words'].split('<br>')
    if len(words) > NUM_WORDS_TO_KEEP:
        words = words[0:NUM_WORDS_TO_KEEP]
    field_map['words'] = '; '.join(words)

    values = []
    for field_name in field_names:  # Preserve order
        value = field_map[field_name]
        html_stripper = MLStripper()
        html_stripper.feed(value)
        value = html_stripper.get_data()
        value = value.replace('#', r'\#')
        value = value.replace('´', "'")
        value = value.replace('{', '"')
        value = value.replace('}', '"')
        value = value.replace(' . . .', '...')
        value = value.replace('_', r'\_')
        value = value.replace('^', '"')
        value = value.replace(' -- ', "---")
        value = value.replace('&', r'\&')
        value = value.replace('$', r'\$')
        value = value.replace('%', r'\%')

        if len(value) > 0:
            if field_name in ['onYomi', 'kunYomi']:
                if value[-1] in ['.', ','] or value[-1] in string.punctuation:
                    value = value[:-1] + '。'
                else:
                    value += '。'
            elif field_name == 'words' or 'story' in field_name.lower():
                if value[-1] not in string.punctuation:
                    value += '.'
            elif field_name == 'keyword':
                value = value.capitalize()

            # End the sentence of words and stories
            value = '{' + value + '}'
        # Done with the value
        values.append(value)
    write_row(fp=fp, row=values)


def write_header(fp: TextIO, row: List[str]):
    vals = []
    eng = inflect.engine()
    for s in row:
        new_s = ""
        for c in s:
            if c.isdigit():
                repl_s = eng.number_to_words(c)
                new_s += repl_s.capitalize()
            else:
                new_s += c
        vals.append(new_s)
    write_row(fp, vals)


def main(args: List[str]) -> int:
    fields = get_fields()
    cur = db.cursor()
    cur.execute("select id, flds, sfld from notes")
    rows = cur.fetchall()
    media_mapping = {v: k for k, v in get_media_mapping().items()}

    SELECTED_FIELDS = [
        'id',
        'kanji',
        'strokeDiagram',
        'heisigStory',
        'onYomi',
        'kunYomi',
        'words',
        'jlpt',
        'jouYou',
        'keyword',
        'constituent'
    ]
    RENAMED_FIELDS = [
        'id',
        'kanji',
        'strokeDiagram',
        'story',
        'onYomi',
        'kunYomi',
        'words',
        'jlpt',
        'jouYou',
        'keyword',
        'constituent'
    ]

    out_rows: List[Dict[str, str]] = []
    for row in rows:
        flds = row[1]
        values = flds.split('\x1f')
        assert len(fields) == len(fields)
        field_map = dict(zip(fields, values))
        stroke_diagram = field_map['strokeDiagram']
        m = re.findall(r'<img src="(.*)".*/>', stroke_diagram)

        stroke_diagram = media_mapping[m[0]]
        src_file = INPUT_DIR / stroke_diagram
        if not src_file.exists():
            print(f"File {src_file} not found, skipping. Kanji: {field_map}")
            continue
        dst_file = MEDIA_OUTPUT_DIR / f"{stroke_diagram}.png"
        process_stroke(src_path=src_file, dst_path=dst_file)
        stroke_diagram = MEDIA_PREFIX + stroke_diagram
        field_map['strokeDiagram'] = stroke_diagram
        out_rows.append(field_map)

    with open(OUTPUT_FILE, 'w') as fp:
        write_header(fp, RENAMED_FIELDS)
        for row in sorted(out_rows, key=lambda x: int(x['id'])):
            write_kanji(fp=fp, field_names=SELECTED_FIELDS, field_map=row)
        fp.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
