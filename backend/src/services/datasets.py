from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.models import Dataset
from src.services.business import metadata
from src.utils.serialization import checksum
import math, time
from datetime import date


def create(db, data):
    name = data.name.strip()
    if len(name) < 2: raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    if db.scalar(select(Dataset).where(Dataset.name == name)):
        raise HTTPException(409, '该数据批次名已存在，请修改名称')
    for index, row in enumerate(data.records):
        for c in metadata()['columns']:
            value = row.get(c['key'])
            if value is None or value == '': raise HTTPException(422, f'第 {index+1} 行缺少字段 {c["label"]}')
            if c['type'] == 'number':
                try:
                    if isinstance(value, bool) or not math.isfinite(float(value)): raise ValueError()
                    row[c['key']] = float(value)
                except (TypeError, ValueError, OverflowError): raise HTTPException(422, f'第 {index+1} 行 {c["label"]} 必须为有限数值')
    d = Dataset(name=name, source=data.source, records=data.records, checksum=checksum(data.records), created_at=time.time())
    db.add(d); db.flush()
    return d


def _normalized_rows(records):
    """校验补账源账；任何一行不合格都整批拒绝，不做部分写入。"""
    columns = metadata()['columns']
    keys = {c['key'] for c in columns}
    labels = {c['key']: c['label'] for c in columns}
    numbers = {c['key'] for c in columns if c['type'] == 'number'}
    rows, seen = [], set()
    for index, row in enumerate(records):
        if not isinstance(row, dict):
            raise HTTPException(422, f'第 {index+1} 行必须为对象')
        unknown = set(row) - keys
        if unknown:
            raise HTTPException(422, f'第 {index+1} 行包含未注册字段：{", ".join(sorted(map(str, unknown)))}')
        for c in columns:
            value = row.get(c['key'])
            if value is None or (isinstance(value, str) and not value.strip()):
                raise HTTPException(422, f'第 {index+1} 行缺少字段 {c["label"]}')
        try:
            day = date.fromisoformat(str(row['day']).strip())
        except (TypeError, ValueError):
            raise HTTPException(422, f'第 {index+1} 行日期必须为 YYYY-MM-DD') from None
        channel = str(row['channel']).strip()
        if not channel: raise HTTPException(422, f'第 {index+1} 行渠道不能为空')
        currency = str(row['currency']).strip()
        if currency != 'CNY':
            raise HTTPException(422, f'第 {index+1} 行币种为 {currency}；补账只接受统一CNY')
        values = {}
        for key in numbers:
            try:
                if isinstance(row[key], bool): raise ValueError()
                value = float(row[key])
            except (TypeError, ValueError, OverflowError):
                raise HTTPException(422, f'第 {index+1} 行 {labels[key]} 必须为数值') from None
            if not math.isfinite(value) or not 0 <= value <= 1_000_000_000:
                raise HTTPException(422, f'第 {index+1} 行 {labels[key]} 必须为0至10亿之间的有限数值')
            values[key] = value
        if not values['visits'].is_integer():
            raise HTTPException(422, f'第 {index+1} 行访问数必须为整数，不能提交已经平均化的分母')
        key = (day, channel)
        if key in seen:
            raise HTTPException(422, f'第 {index+1} 行日期 {day} + 渠道 {channel} 在补账内重复，整批拒绝')
        seen.add(key)
        values.update({'day': day.isoformat(), 'channel': channel, 'currency': 'CNY'})
        rows.append(values)
    return rows


def _record_key(record):
    try:
        day = date.fromisoformat(str(record['day']).strip())
        channel = str(record['channel']).strip()
    except (KeyError, TypeError, ValueError):
        raise HTTPException(409, '原批次源账缺少可解析的日期或渠道，无法合并补账') from None
    return day.isoformat(), channel


def _supplement_name(parent, data, digest):
    name = (data.name or '').strip()
    if name:
        if len(name) < 2: raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
        return name
    return parent.name[:140] + ' · 补账 ' + digest[:8]


def supplement(db, parent_id, data):
    """把补账并入所选原批次，生成新的不可变批次；原批次与其既有结果不动。

    同日同渠道整行替换、新日期追加、其余源账保留。相同补账重复提交时返回首个
    生成的批次，不产生第二份。不同补账各自生成独立子批次，保留各自来源。
    """
    parent = db.get(Dataset, parent_id)
    if not parent: raise HTTPException(404, '原数据批次不存在')
    rows = _normalized_rows(data.records)
    digest = checksum({'parent_id': parent.id, 'records': rows})

    existing = db.scalar(select(Dataset).where(Dataset.parent_id == parent.id, Dataset.supplement_hash == digest))
    if existing: return existing, True
    name = _supplement_name(parent, data, digest)
    same_name = db.scalar(select(Dataset).where(Dataset.name == name))
    if same_name:
        if same_name.parent_id == parent.id and same_name.supplement_hash == digest:
            return same_name, True
        raise HTTPException(409, '该数据批次名已存在，请修改名称')

    parent_keys = {}
    for index, record in enumerate(parent.records):
        key = _record_key(record)
        if key in parent_keys:
            raise HTTPException(409, f'原批次第 {index+1} 行日期 {key[0]} + 渠道 {key[1]} 自然键重复，无法补账')
        parent_keys[key] = record
    supplement_by_key = {(row['day'], row['channel']): row for row in rows}

    merged, replaced, added = [], [], []
    for record in parent.records:
        key = _record_key(record)
        replacement = supplement_by_key.get(key)
        if replacement is not None:
            merged.append(replacement)
            replaced.append({'day': replacement['day'], 'channel': replacement['channel'], 'previous': record, 'current': replacement})
        else:
            merged.append(record)
    for row in rows:
        key = (row['day'], row['channel'])
        if key not in parent_keys:
            merged.append(row)
            added.append({'day': row['day'], 'channel': row['channel'], 'record': row})

    merge_detail = {
        'parent_id': parent.id, 'parent_name': parent.name, 'parent_checksum': parent.checksum,
        'base_rows': len(parent.records), 'supplement_rows': len(rows),
        'replaced_rows': len(replaced), 'added_rows': len(added), 'retained_rows': len(merged) - len(replaced) - len(added),
        'merged_rows': len(merged), 'supplement_checksum': digest,
        'replaced': replaced, 'added': added,
    }
    d = Dataset(name=name, source=data.source, records=merged, checksum=checksum(merged), created_at=time.time(),
                parent_id=parent.id, kind='supplement', supplement_hash=digest, merge_detail=merge_detail)
    try:
        with db.begin_nested():
            db.add(d)
        db.flush()
    except IntegrityError:
        # 并发重复补发：唯一约束只允许一份，返回已落库的补账。
        existing = db.scalar(select(Dataset).where(Dataset.parent_id == parent_id, Dataset.supplement_hash == digest))
        if existing: return existing, True
        raise HTTPException(409, '补账批次名称或内容与现有批次冲突，请检查后重试') from None
    return d, False
