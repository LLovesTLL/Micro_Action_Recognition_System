from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..core.config import settings
from .video_service import sample_video_frames


REPORT_TITLE = '微动作识别推理报告'


def _register_cjk_font() -> str:
    candidates = [
        Path(r'C:\Windows\Fonts\simhei.ttf'),
        Path(r'C:\Windows\Fonts\simsunb.ttf'),
        Path(r'C:\Windows\Fonts\NotoSansSC-VF.ttf'),
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        font_name = f'CJK_{candidate.stem}'
        try:
            pdfmetrics.registerFont(TTFont(font_name, str(candidate)))
            return font_name
        except Exception:
            continue
    return 'Helvetica'


FONT_NAME = _register_cjk_font()


def _now_local() -> str:
    return datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S')


def _text(value: Any, default: str = '-') -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _num_text(value: Any, digits: int = 2, default: str = '-') -> str:
    try:
        return f'{float(value):.{digits}f}'
    except Exception:
        return default


def _percent_text(value: Any) -> str:
    try:
        return f'{float(value) * 100:.1f}%'
    except Exception:
        return '-'


def _extract_summary(payload: dict[str, Any]) -> dict[str, Any]:
    inference_raw = payload.get('inference')
    inference: dict[str, Any] = inference_raw if isinstance(inference_raw, dict) else {}
    return {
        'video_name': _text(payload.get('source_filename') or payload.get('filename') or inference.get('filename')),
        'top_class': _text(payload.get('top_class') or inference.get('top_class') or inference.get('prediction')),
        'top_confidence': float(payload.get('top_confidence') or inference.get('top_confidence') or 0.0),
        'duration_sec': payload.get('duration_sec') or inference.get('duration_sec'),
        'total_time_ms': payload.get('total_time_ms') or inference.get('total_time_ms'),
        'inference_time_ms': payload.get('inference_time_ms') or inference.get('inference_time_ms'),
        'remote_device': _text(payload.get('remote_device') or inference.get('remote_device') or payload.get('device')),
        'temporal_source': _text(payload.get('temporal_source')),
        'attention_source': _text(payload.get('attention_source')),
        'attention_hook_mode': _text(payload.get('attention_hook_mode')),
        'attention_normalization_mode': _text(payload.get('attention_normalization_mode')),
        'attention_hotspot_threshold': payload.get('attention_hotspot_threshold'),
    }


def _build_styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        'title': ParagraphStyle(
            'title',
            parent=sample['Title'],
            fontName=FONT_NAME,
            fontSize=20,
            leading=24,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#0f172a'),
            spaceAfter=4 * mm,
        ),
        'meta': ParagraphStyle(
            'meta',
            parent=sample['BodyText'],
            fontName=FONT_NAME,
            fontSize=9,
            leading=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#475569'),
            spaceAfter=1.5 * mm,
        ),
        'section': ParagraphStyle(
            'section',
            parent=sample['Heading2'],
            fontName=FONT_NAME,
            fontSize=13,
            leading=16,
            textColor=colors.HexColor('#0f172a'),
            spaceBefore=3 * mm,
            spaceAfter=2.5 * mm,
        ),
        'body': ParagraphStyle(
            'body',
            parent=sample['BodyText'],
            fontName=FONT_NAME,
            fontSize=9.4,
            leading=12.5,
            textColor=colors.HexColor('#1f2937'),
        ),
        'small': ParagraphStyle(
            'small',
            parent=sample['BodyText'],
            fontName=FONT_NAME,
            fontSize=8.2,
            leading=10,
            textColor=colors.HexColor('#475569'),
        ),
        'table_head': ParagraphStyle(
            'table_head',
            parent=sample['BodyText'],
            fontName=FONT_NAME,
            fontSize=8.6,
            leading=10.5,
            textColor=colors.HexColor('#0f172a'),
        ),
        'table_cell': ParagraphStyle(
            'table_cell',
            parent=sample['BodyText'],
            fontName=FONT_NAME,
            fontSize=8.4,
            leading=10.2,
            textColor=colors.HexColor('#111827'),
        ),
    }


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def _metrics_table(styles: dict[str, ParagraphStyle], summary: dict[str, Any]) -> Table:
    rows = [
        ('视频名称', summary['video_name']),
        ('识别类别', summary['top_class']),
        ('Top-1 置信度', _percent_text(summary['top_confidence'])),
        ('视频时长', f"{_num_text(summary['duration_sec'])} s" if summary['duration_sec'] is not None else '-'),
        ('总耗时', f"{_num_text(summary['total_time_ms'])} ms"),
        ('纯推理耗时', f"{_num_text(summary['inference_time_ms'])} ms"),
        ('远端设备', summary['remote_device']),
        ('时序来源', summary['temporal_source']),
        ('注意力来源', summary['attention_source']),
        ('注意力挂钩模式', summary['attention_hook_mode']),
        ('注意力归一化', summary['attention_normalization_mode']),
        ('热点阈值', _num_text(summary['attention_hotspot_threshold'])),
    ]

    data = [[_paragraph('<b>字段</b>', styles['table_head']), _paragraph('<b>值</b>', styles['table_head'])]]
    for key, value in rows:
        data.append([_paragraph(key, styles['table_cell']), _paragraph(value, styles['table_cell'])])

    table = Table(data, colWidths=[40 * mm, 124 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
                ('GRID', (0, 0), (-1, -1), 0.55, colors.HexColor('#d7dee8')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 4.5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4.5),
            ]
        )
    )
    return table


def _topk_table(styles: dict[str, ParagraphStyle], payload: dict[str, Any]) -> Table:
    topk = payload.get('topk') if isinstance(payload.get('topk'), list) else []
    rows = [[_paragraph('<b>类别</b>', styles['table_head']), _paragraph('<b>置信度</b>', styles['table_head'])]]

    if topk:
        for item in topk[:5]:
            if not isinstance(item, dict):
                continue
            rows.append(
                [
                    _paragraph(_text(item.get('label')), styles['table_cell']),
                    _paragraph(_percent_text(item.get('confidence')), styles['table_cell']),
                ]
            )
    else:
        rows.append([_paragraph(_text(payload.get('top_class')), styles['table_cell']), _paragraph(_percent_text(payload.get('top_confidence')), styles['table_cell'])])

    table = Table(rows, colWidths=[120 * mm, 40 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eaf2ff')),
                ('GRID', (0, 0), (-1, -1), 0.55, colors.HexColor('#d7dee8')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _temporal_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    points = payload.get('temporal_probs')
    if not isinstance(points, list):
        return []
    clean: list[dict[str, Any]] = []
    for item in points:
        if isinstance(item, dict) and isinstance(item.get('probs'), dict):
            clean.append(item)
    return clean


def _data_url_to_file(data_url: str, out_path: Path) -> bool:
    if not isinstance(data_url, str) or not data_url.startswith('data:image/'):
        return False
    match = re.match(r'^data:image/[^;]+;base64,(.+)$', data_url)
    if not match:
        return False
    try:
        out_path.write_bytes(base64.b64decode(match.group(1)))
        return True
    except Exception:
        return False


def _save_plot_temporal_probs(temporal_probs: list[dict[str, Any]], out_path: Path) -> None:
    first = temporal_probs[0]
    classes = list(first.get('probs', {}).keys())[:6]
    times = [float(p.get('t', 0.0)) for p in temporal_probs]

    plt.figure(figsize=(9.6, 3.2))
    ax = plt.gca()
    palette = ['#ff7a59', '#ffb366', '#ffe08a', '#6fd6ff', '#8cffc9', '#ff9ecb']
    for idx, name in enumerate(classes):
        vals = [float(p.get('probs', {}).get(name, 0.0)) for p in temporal_probs]
        ax.plot(times, vals, linewidth=2.1, color=palette[idx % len(palette)], label=name)

    ax.set_ylim(0, 1)
    ax.set_xlim(min(times), max(times) if len(times) > 1 else min(times) + 1)
    ax.set_xlabel('时间 (s)')
    ax.set_ylabel('概率')
    ax.grid(True, alpha=0.22)
    ax.legend(loc='upper right', fontsize=8, frameon=False, ncol=2)
    plt.tight_layout()
    plt.savefig(out_path, dpi=170, bbox_inches='tight')
    plt.close()


def _save_thumbnails_from_video(video_path: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    thumbs: list[Path] = []
    try:
        samples, _ = sample_video_frames(video_path, max_points=4)
        for i, sample in enumerate(samples):
            img_path = out_dir / f'thumb_{i}.png'
            Image.fromarray(sample.frame[:, :, ::-1]).save(img_path)
            thumbs.append(img_path)
    except Exception:
        return []
    return thumbs


def _resolve_chart_image(payload: dict[str, Any], temp_dir: Path) -> Path | None:
    chart_data_url = payload.get('chart_data_url')
    chart_path = temp_dir / 'temporal_chart.png'
    if _data_url_to_file(str(chart_data_url or ''), chart_path):
        return chart_path

    temporal_points = _temporal_points(payload)
    if not temporal_points:
        return None
    try:
        _save_plot_temporal_probs(temporal_points, chart_path)
        return chart_path
    except Exception:
        return None


def _resolve_heatmap_image(payload_item: dict[str, Any]) -> Path | None:
    heatmap_path = _text(payload_item.get('heatmap_path') or payload_item.get('path') or payload_item.get('src'), '')
    if not heatmap_path:
        return None
    filename = Path(heatmap_path).name
    candidate = settings.output_dir / filename
    if candidate.exists():
        return candidate
    return None


def _heatmap_table(payload: dict[str, Any]) -> Table | None:
    heatmaps = payload.get('heatmaps')
    heatmap_paths = payload.get('heatmap_paths')

    if isinstance(heatmap_paths, list) and heatmap_paths:
        heatmaps = [{'heatmap_path': path, 't': idx} for idx, path in enumerate(heatmap_paths)]

    if not isinstance(heatmaps, list) or not heatmaps:
        return None

    rows: list[list[Any]] = []
    current_row: list[Any] = []
    for item in heatmaps[:4]:
        if not isinstance(item, dict):
            continue
        if isinstance(item, str):
            item = {'heatmap_path': item}
        image_path = _resolve_heatmap_image(item)
        if not image_path:
            continue
        figure = [
            RLImage(str(image_path), width=39 * mm, height=28 * mm),
            Spacer(1, 1.4 * mm),
            _paragraph(f"{_num_text(item.get('t'))}s", ParagraphStyle('cap', fontName=FONT_NAME, fontSize=8.1, leading=9.5, alignment=TA_CENTER, textColor=colors.HexColor('#475569'))),
        ]
        current_row.append(figure)
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []

    if current_row:
        rows.append(current_row)

    if not rows:
        return None

    table = Table(rows, colWidths=[82 * mm, 82 * mm], hAlign='LEFT')
    table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    return table


def generate_pdf_report(payload: dict[str, Any], source_video_path: Path | None = None) -> Path:
    out_dir = settings.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    report_path = out_dir / f'inference_report_{uuid4().hex}.pdf'
    temp_dir = out_dir / f'_report_tmp_{uuid4().hex}'
    temp_dir.mkdir(parents=True, exist_ok=True)

    summary = _extract_summary(payload)
    styles = _build_styles()
    story: list[Any] = []

    story.append(Spacer(1, 4 * mm))

    story.append(_paragraph('一、视频与推理概览', styles['section']))
    story.append(_metrics_table(styles, summary))
    story.append(Spacer(1, 4.5 * mm))

    story.append(_paragraph('二、Top-K 结果', styles['section']))
    story.append(_topk_table(styles, payload))
    story.append(Spacer(1, 4.5 * mm))

    story.append(_paragraph('三、时序概率曲线', styles['section']))
    chart_image = _resolve_chart_image(payload, temp_dir)
    if chart_image and chart_image.exists():
        story.append(RLImage(str(chart_image), width=166 * mm, height=50 * mm))
    else:
        story.append(_paragraph('未获取到时序概率曲线。', styles['small']))
    story.append(Spacer(1, 4.5 * mm))

    story.append(_paragraph('四、Attention 热力图', styles['section']))
    heatmap_table = _heatmap_table(payload)
    if heatmap_table:
        story.append(heatmap_table)
    else:
        story.append(_paragraph('未获取到 attention 热力图。', styles['small']))

    doc = SimpleDocTemplate(
        str(report_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=REPORT_TITLE,
        author='Micro Action Recognition System',
    )

    try:
        doc.build(story)
    finally:
        for child in temp_dir.glob('**/*'):
            try:
                if child.is_file():
                    child.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            temp_dir.rmdir()
        except Exception:
            pass

    return report_path
