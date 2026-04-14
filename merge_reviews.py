from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

OUTPUT_COLUMNS = [
    'code',
    'itemid',
    'shopid',
    'rating_star',
    'sample_index',
    'rating_id',
    'author_username',
    'like_count',
    'ctime',
    't_ctime',
    'comment',
    'product_items',
    'insert_date',
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Merge Shopee review CSV files.')
    parser.add_argument(
        '--input-dir',
        default='.',
        help='Thư mục gốc để quét các file shopee_reviews_*.csv (quét đệ quy).',
    )
    parser.add_argument(
        '--pattern',
        default='shopee_reviews_*.csv',
        help='Glob pattern cho file CSV cần gộp.',
    )
    parser.add_argument(
        '--output',
        default='merged_reviews.csv',
        help='Tên file CSV đầu ra.',
    )
    return parser.parse_args()


def normalize_text(value: object) -> str:
    if pd.isna(value):
        return ''
    text = str(value).strip()
    if text.endswith('.0'):
        text = text[:-2]
    return text


def derive_code(csv_path: Path, frame: pd.DataFrame) -> str:
    match = re.match(r'shopee_reviews_(\d+)_(\d+)_\d+\.csv$', csv_path.name)
    if match:
        return f'{match.group(1)}_{match.group(2)}'

    if not frame.empty and {'shopid', 'itemid'}.issubset(frame.columns):
        shop_values = frame['shopid'].dropna().astype(str).str.strip()
        item_values = frame['itemid'].dropna().astype(str).str.strip()
        if not shop_values.empty and not item_values.empty:
            shop_text = normalize_text(shop_values.iloc[0])
            item_text = normalize_text(item_values.iloc[0])
            if shop_text and item_text:
                return f'{shop_text}_{item_text}'

    return csv_path.stem


def load_review_file(csv_path: Path) -> pd.DataFrame | None:
    try:
        frame = pd.read_csv(csv_path, encoding='utf-8-sig')
    except Exception as error:
        print(f'  ✗ {csv_path}: {error}')
        return None

    for column in OUTPUT_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA

    code_value = derive_code(csv_path, frame)
    frame['code'] = frame['code'].apply(normalize_text)
    frame.loc[frame['code'] == '', 'code'] = code_value

    frame['itemid'] = frame['itemid'].apply(normalize_text)
    frame['shopid'] = frame['shopid'].apply(normalize_text)
    frame['rating_id'] = frame['rating_id'].apply(normalize_text)
    frame['t_ctime'] = frame['t_ctime'].fillna('')
    frame['comment'] = frame['comment'].fillna('')
    frame['product_items'] = frame['product_items'].fillna('')
    frame['insert_date'] = frame['insert_date'].fillna('')

    for column in ['rating_star', 'sample_index', 'like_count', 'ctime']:
        frame[column] = pd.to_numeric(frame[column], errors='coerce')

    frame = frame[OUTPUT_COLUMNS]
    print(f'  ✓ {csv_path}: {len(frame)} reviews')
    return frame


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_dir).resolve()
    files = sorted(path for path in input_dir.rglob(args.pattern) if path.is_file())

    if not files:
        print('❌ Không tìm thấy file CSV nào!')
        return 1

    print(f'📂 Tìm thấy {len(files)} file CSV trong {input_dir}')

    df_list: list[pd.DataFrame] = []
    for csv_path in files:
        frame = load_review_file(csv_path)
        if frame is not None:
            df_list.append(frame)

    if not df_list:
        print('❌ Không đọc được file nào!')
        return 1

    merged = pd.concat(df_list, ignore_index=True)
    print(f'\n📊 Tổng: {len(merged)} reviews (trước khi xóa trùng)')

    merged = merged.drop_duplicates(subset=['rating_id'], keep='first')
    print(f'📊 Sau khi xóa trùng: {len(merged)} reviews')

    merged = merged.sort_values(['code', 'shopid', 'itemid', 'rating_star', 'sample_index', 'ctime'])

    output_path = Path(args.output).resolve()
    merged.to_csv(output_path, index=False, encoding='utf-8-sig')

    print(f'\n✅ Đã lưu vào: {output_path}')
    print('📈 Thống kê theo sao:')
    star_series = pd.to_numeric(merged['rating_star'], errors='coerce').fillna(0).astype(int)
    for star in range(1, 6):
        count = int((star_series == star).sum())
        print(f'  {star}★: {count} reviews')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
