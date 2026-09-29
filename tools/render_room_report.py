"""Render a saved PitDivers room into standalone SVG maps and an HTML report.

Standard library only. Input can be a saved JSON file or the dashboard export URL.
Environmental colours are measured samples, not whole-room interpolation.
"""
import argparse
import html
import json
import math
from pathlib import Path
from urllib.request import urlopen


def render(room, field=None):
    cells=room['cells']; resolution=float(room['resolution'])
    if not cells or not math.isfinite(resolution) or resolution<=0:
        raise ValueError('Map requires cells and a positive resolution')
    lo_x=min(c[0] for c in cells)*resolution
    lo_y=min(c[1] for c in cells)*resolution
    hi_x=(max(c[0] for c in cells)+1)*resolution
    hi_y=(max(c[1] for c in cells)+1)*resolution
    scale=min(900/max(hi_x-lo_x,.1),660/max(hi_y-lo_y,.1))
    def xy(x,y):return 70+(x-lo_x)*scale,90+(hi_y-y)*scale
    labels={None:('LiDAR floor plan',''),2:('Temperature measurements','°C'),3:('Humidity measurements','% RH')}
    title,unit=labels[field]
    samples=[p for p in room.get('environment',[]) if len(p)>=6 and
             all(isinstance(p[i],(int,float)) and math.isfinite(p[i]) for i in (0,1,2,3,5)) and 0<=p[5]<=3000]
    values=[p[field] for p in samples] if field is not None else []
    low,high=(min(values),max(values)) if values else (0,0)
    def colour(value):
        t=.5 if high==low else (value-low)/(high-low)
        return f'rgb({int(40+205*t)},{int(150-65*t)},{int(220-165*t)})'
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1040 920" role="img" aria-label="{title}">',
           '<rect width="1040" height="920" fill="#f7f9fc"/>',
           f'<text x="40" y="38" font-size="25" font-family="sans-serif" fill="#15283b">{title}</text>',
           '<text x="40" y="65" font-size="14" font-family="sans-serif">Metres in the saved map frame · same scale and orientation in all layers</text>']
    for x,y,occupancy in cells:
        px,py=xy(x*resolution,(y+1)*resolution)
        fill='#33465a' if occupancy==8 else '#e0e8ef' if occupancy==-8 else '#f1f4f7'
        parts.append(f'<rect x="{px:.2f}" y="{py:.2f}" width="{resolution*scale+.05:.2f}" height="{resolution*scale+.05:.2f}" fill="{fill}"/>')
    path=room.get('path',[])
    if path:
        points=' '.join(f'{x:.2f},{y:.2f}' for x,y in (xy(p[0],p[1]) for p in path))
        parts.append(f'<polyline points="{points}" fill="none" stroke="#008675" stroke-width="1.5" opacity=".7"/>')
        for label,p in [('Start',path[0]),('Finish',path[-1])]:
            x,y=xy(p[0],p[1]);parts.append(f'<circle cx="{x}" cy="{y}" r="5" fill="#008675"/><text x="{x+8}" y="{y-8}" font-family="sans-serif" font-size="12">{label}</text>')
    if field is not None:
        label_boxes=[]
        value_labels=[]
        for p in samples:
            x,y=xy(p[0],p[1]);value=p[field]
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="7" fill="{colour(value)}" stroke="white" stroke-width="1"><title>{value:.1f} {unit}; x={p[0]:.2f} m, y={p[1]:.2f} m; scan {p[4]}</title></circle>')
            # Label spatially distinct measurements; the table retains every sample.
            text=f'{value:.1f} {unit}';width=len(text)*8+16
            box=(x+11,y-24,x+11+width,y)
            if box[2]>1000:box=(x-11-width,y-24,x-11,y)
            if not any(box[0]<b[2]+8 and box[2]>b[0]-8 and box[1]<b[3]+10 and box[3]>b[1]-10 for b in label_boxes):
                label_boxes.append(box)
                value_labels.append(f'<rect x="{box[0]:.2f}" y="{box[1]:.2f}" width="{width}" height="24" rx="5" fill="white" stroke="#78899b"/><text x="{box[0]+8:.2f}" y="{box[1]+17:.2f}" font-family="sans-serif" font-size="14" font-weight="600" fill="#15283b">{text}</text>')
        parts.extend(value_labels)
        if values:
            for i in range(100):
                parts.append(f'<rect x="{40+i*3}" y="804" width="3.1" height="16" fill="{colour(low+(high-low)*i/99)}"/>')
            caption=f'{low:.1f}–{high:.1f} {unit} · {len(samples)} positioned readings · colour scale spans measured range'
        else:caption='No valid positioned readings in this saved room'
        parts.append(f'<text x="40" y="844" font-family="sans-serif" font-size="15">{caption}</text>')
        parts.append('<text x="40" y="870" font-family="sans-serif" font-size="14">Labels show spaced samples; the report table lists every reading. Blank areas are unmeasured.</text>')
    else:
        parts.append('<text x="40" y="844" font-family="sans-serif" font-size="15">Dark: occupied · light: observed free space · green: rover route</text>')
    bar=min(1,(hi_x-lo_x)/3)
    parts.append(f'<path d="M40 780 h{bar*scale:.2f}" stroke="#15283b" stroke-width="3"/><text x="40" y="770" font-family="sans-serif" font-size="13">{bar:g} m</text></svg>')
    return '\n'.join(parts)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',help='JSON file or http(s) export URL')
    parser.add_argument('--output',default='data/reports/latest')
    args=parser.parse_args()
    if args.source.startswith(('http://','https://')):
        with urlopen(args.source,timeout=10) as response:data=json.load(response)
    else:data=json.loads(Path(args.source).read_text(encoding='utf-8-sig'))
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    (output/'source.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    for name,field in [('map',None),('temperature',2),('humidity',3)]:
        (output/f'{name}.svg').write_text(render(data['map'],field),encoding='utf-8')
    ident=html.escape(str(data.get('run_id','Saved room')))
    page=f'<!doctype html><meta charset="utf-8"><title>Room report {ident}</title><style>body{{font:16px system-ui;background:#f7f9fc;color:#15283b;max-width:1040px;margin:24px auto}}img{{width:100%}}section{{break-inside:avoid;page-break-after:always}}@media print{{button{{display:none}}}}</style><h1>Room inspection · {ident}</h1><p>Saved LiDAR map and positioned environmental readings. Sensor values describe air at the rover, not wall surface temperature.</p><button onclick="print()">Print / save as PDF</button>'
    for name in ['map','temperature','humidity']:
        page+=f'<section><img src="{name}.svg" alt="{name} layer"></section>'
    page+='<style>table{width:100%;border-collapse:collapse}th,td{padding:9px;text-align:right;border-bottom:1px solid #cbd5e1}thead{display:table-header-group}tr{break-inside:avoid}</style><h2>All environmental readings</h2><p>Coordinates in metres. Repeated readings at the same location are retained.</p><table><thead><tr><th>Sample</th><th>X (m)</th><th>Y (m)</th><th>Temperature (°C)</th><th>Humidity (% RH)</th><th>Reading age (ms)</th></tr></thead><tbody>'
    for i,p in enumerate(data['map'].get('environment',[]),1):
        if len(p)<6:continue
        def number(v,digits=1):
            return f'{v:.{digits}f}' if isinstance(v,(int,float)) and math.isfinite(v) else '—'
        page+=f'<tr><td>{i}</td><td>{number(p[0],2)}</td><td>{number(p[1],2)}</td><td>{number(p[2])}</td><td>{number(p[3])}</td><td>{number(p[5],0)}</td></tr>'
    page+='</tbody></table>'
    (output/'report.html').write_text(page,encoding='utf-8')
    print((output/'report.html').resolve())


if __name__=='__main__':main()
