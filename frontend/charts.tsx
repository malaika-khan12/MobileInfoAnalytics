"use client";

import type { CSSProperties } from "react";
import type { JsonRecord } from "./live-api";

const COLORS = ["#213d31", "#355e4b", "#6b705c", "#a7b88d", "#4f7966", "#899b72", "#c3ceb0"];

function number(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function label(value: unknown): string {
  return value === null || value === undefined || value === "" ? "Unknown" : String(value);
}

function compact(value: number): string {
  return Intl.NumberFormat(undefined, { notation: value >= 1000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value);
}

export function SourceCoverageChart({ rows }: { rows: JsonRecord[] }) {
  if (!rows.length) return <div className="table-empty">No source rows returned.</div>;
  const data = [...rows].sort((a, b) => number(b.total_listings) - number(a.total_listings));
  const max = Math.max(1, ...data.map((row) => number(row.total_listings)));
  const width = 940;
  const height = 360;
  const left = 62;
  const right = 58;
  const top = 28;
  const bottom = 82;
  const innerWidth = width - left - right;
  const innerHeight = height - top - bottom;
  const band = innerWidth / Math.max(1, data.length);
  const barWidth = Math.min(72, band * .58);
  const points = data.map((row, index) => {
    const x = left + band * index + band / 2;
    const quality = Math.max(0, Math.min(100, number(row.avg_data_completeness_pct)));
    return `${x},${top + innerHeight * (1 - quality / 100)}`;
  }).join(" ");

  return <div className="chart-card-body" role="img" aria-label="Source listings and completeness">
    <svg className="dashboard-svg" viewBox={`0 0 ${width} ${height}`}>
      {[0, .25, .5, .75, 1].map((ratio) => {
        const y = top + innerHeight * (1 - ratio);
        return <g key={ratio}><line x1={left} x2={width-right} y1={y} y2={y} className="svg-grid"/><text x={left-10} y={y+4} textAnchor="end">{compact(max*ratio)}</text><text x={width-right+10} y={y+4}>{Math.round(ratio*100)}%</text></g>;
      })}
      {data.map((row, index) => {
        const listings = number(row.total_listings);
        const h = innerHeight * listings / max;
        const x = left + band * index + (band-barWidth)/2;
        return <g key={label(row.source_domain)}>
          <title>{`${label(row.source_domain)} · ${listings.toLocaleString()} listings · ${number(row.avg_data_completeness_pct).toFixed(1)}% complete`}</title>
          <rect x={x} y={top+innerHeight-h} width={barWidth} height={h} rx="8" className="coverage-bar"/>
          <text x={x+barWidth/2} y={height-bottom+24} textAnchor="end" transform={`rotate(-28 ${x+barWidth/2} ${height-bottom+24})`}>{label(row.source_domain)}</text>
        </g>;
      })}
      <polyline points={points} className="quality-line" />
      {data.map((row,index) => {
        const x=left+band*index+band/2;
        const quality=Math.max(0,Math.min(100,number(row.avg_data_completeness_pct)));
        const y=top+innerHeight*(1-quality/100);
        return <circle key={`q-${index}`} cx={x} cy={y} r="6" className="quality-dot"><title>{`${label(row.source_domain)} · ${quality.toFixed(1)}% completeness`}</title></circle>;
      })}
    </svg>
    <div className="chart-legend"><span><i className="legend-swatch listings"/>Market listings</span><span><i className="legend-swatch quality"/>Average completeness</span></div>
  </div>;
}

export function BarList({ rows, valueLabel = "products" }: { rows: { label?: unknown; count?: unknown }[]; valueLabel?: string }) {
  if (!rows.length) return <div className="table-empty">No analytics sample rows returned.</div>;
  const max = Math.max(1, ...rows.map((row) => number(row.count)));
  return <div className="bar-list">
    {rows.map((row, index) => {
      const value = number(row.count);
      return <div className="bar-list-row" key={`${label(row.label)}-${index}`}>
        <span>{label(row.label)}</span><div className="bar-list-track"><i style={{ width: `${Math.max(2, value/max*100)}%`, background: COLORS[index%COLORS.length] }} /></div><strong>{value.toLocaleString()}</strong><small>{valueLabel}</small>
      </div>;
    })}
  </div>;
}

export function DonutChart({ rows, center }: { rows: { label?: unknown; count?: unknown }[]; center: string }) {
  if (!rows.length) return <div className="table-empty">No composition rows returned.</div>;
  const total = rows.reduce((sum,row) => sum + number(row.count), 0) || 1;
  let offset = 0;
  const radius = 62;
  const circumference = 2*Math.PI*radius;
  return <div className="donut-layout">
    <svg className="donut-svg" viewBox="0 0 180 180" aria-label="Composition donut">
      <circle cx="90" cy="90" r={radius} className="donut-base" />
      {rows.map((row,index) => {
        const value=number(row.count); const ratio=value/total; const dash=ratio*circumference; const current=offset; offset += dash;
        return <circle key={`${label(row.label)}-${index}`} cx="90" cy="90" r={radius} fill="none" stroke={COLORS[index%COLORS.length]} strokeWidth="28" strokeDasharray={`${dash} ${circumference-dash}`} strokeDashoffset={-current} transform="rotate(-90 90 90)"><title>{`${label(row.label)} · ${value.toLocaleString()} · ${(ratio*100).toFixed(1)}%`}</title></circle>;
      })}
      <text x="90" y="86" textAnchor="middle" className="donut-center-main">{center}</text><text x="90" y="105" textAnchor="middle" className="donut-center-sub">sample</text>
    </svg>
    <div className="donut-legend">{rows.slice(0,7).map((row,index)=><div key={`${label(row.label)}-legend`}><i style={{background:COLORS[index%COLORS.length]}}/><span>{label(row.label)}</span><strong>{number(row.count).toLocaleString()}</strong></div>)}</div>
  </div>;
}

export function AdoptionRing({ labelText, value, total }: { labelText: string; value: number; total: number }) {
  const pct = total ? Math.max(0,Math.min(100,value/total*100)) : 0;
  const style = { "--ring-value": `${pct*3.6}deg` } as CSSProperties;
  return <div className="adoption-card"><div className="adoption-ring" style={style}><div><strong>{pct.toFixed(1)}%</strong><span>{labelText}</span></div></div><p>{value.toLocaleString()} of {total.toLocaleString()} sampled canonical products</p></div>;
}

export function PriceRanges({ rows }: { rows: JsonRecord[] }) {
  const data = rows.filter((row)=>number(row.max_price)>0).slice(0,14);
  if (!data.length) return <div className="table-empty">No price comparison rows returned.</div>;
  const max = Math.max(1,...data.map((row)=>number(row.max_price)));
  return <div className="price-range-list">
    {data.map((row,index)=>{
      const min=number(row.min_price), avg=number(row.avg_price), high=number(row.max_price);
      const left=min/max*100, right=high/max*100, avgPos=avg/max*100;
      return <div className="price-range-row" key={`${row.product_id ?? index}-${label(row.currency_code)}`}>
        <div className="price-product"><strong>{label(row.company_name)} {label(row.mobile_name)}</strong><span>{label(row.currency_code)} · {number(row.sources_count)} source(s)</span></div>
        <div className="price-track"><i className="price-range" style={{left:`${left}%`,width:`${Math.max(.8,right-left)}%`}}/><b className="price-average" style={{left:`${avgPos}%`}}><span>{avg.toLocaleString(undefined,{maximumFractionDigits:0})}</span></b></div>
        <div className="price-minmax"><span>{min.toLocaleString(undefined,{maximumFractionDigits:0})}</span><span>{high.toLocaleString(undefined,{maximumFractionDigits:0})}</span></div>
      </div>;
    })}
  </div>;
}

export function TechnologyScatter({ rows }: { rows: JsonRecord[] }) {
  const data = rows.filter((row)=>number(row.capacity_mah)>0 && number(row.refresh_rate_hz)>0).slice(0,160);
  if (!data.length) return <div className="table-empty">Battery/refresh-rate values are not populated in the current product sample.</div>;
  const width=900,height=380,left=70,right=28,top=24,bottom=54;
  const xValues=data.map((r)=>number(r.capacity_mah)), yValues=data.map((r)=>number(r.refresh_rate_hz));
  const minX=Math.min(...xValues), maxX=Math.max(...xValues), maxY=Math.max(60,...yValues);
  const x=(value:number)=>left+(value-minX)/Math.max(1,maxX-minX)*(width-left-right);
  const y=(value:number)=>top+(1-value/maxY)*(height-top-bottom);
  const screens=[...new Set(data.map((row)=>label(row.screen_technology)))];
  return <div className="chart-card-body"><svg className="dashboard-svg" viewBox={`0 0 ${width} ${height}`}>
    {[0,.25,.5,.75,1].map((ratio)=>{const yy=top+(height-top-bottom)*(1-ratio);return <g key={ratio}><line x1={left} x2={width-right} y1={yy} y2={yy} className="svg-grid"/><text x={left-12} y={yy+4} textAnchor="end">{Math.round(maxY*ratio)}</text></g>})}
    {[0,.25,.5,.75,1].map((ratio)=>{const xx=left+(width-left-right)*ratio;return <g key={`x${ratio}`}><text x={xx} y={height-22} textAnchor="middle">{Math.round(minX+(maxX-minX)*ratio).toLocaleString()}</text></g>})}
    {data.map((row,index)=>{const screen=label(row.screen_technology);const color=COLORS[Math.max(0,screens.indexOf(screen))%COLORS.length];const ppi=Math.max(180,Math.min(650,number(row.pixel_density_ppi)||300));return <circle key={`${row.product_id ?? index}`} cx={x(number(row.capacity_mah))} cy={y(number(row.refresh_rate_hz))} r={4+(ppi-180)/470*7} fill={color} className="tech-dot"><title>{`${label(row.company_name)} ${label(row.mobile_name)} · ${number(row.capacity_mah)} mAh · ${number(row.refresh_rate_hz)} Hz · ${screen} · ${row.supports_5g ? "5G" : "non-5G"}`}</title></circle>})}
    <text x={(left+width-right)/2} y={height-3} textAnchor="middle" className="svg-axis-title">Battery capacity · mAh</text>
  </svg><div className="chart-legend wrap">{screens.slice(0,7).map((screen,index)=><span key={screen}><i style={{background:COLORS[index%COLORS.length]}}/>{screen}</span>)}</div></div>;
}

export function DiscrepancyHeatmap({ rows }: { rows: JsonRecord[] }) {
  if (!rows.length) return <div className="table-empty">No cross-source discrepancy rows returned.</div>;
  const columns: [string,string][] = [["battery_pct","Battery"],["screen_pct","Screen"],["refresh_pct","Refresh"]];
  const max=Math.max(1,...rows.flatMap((row)=>columns.map(([key])=>number(row[key]))));
  function background(value:number){const ratio=Math.max(0,Math.min(1,value/max));return `color-mix(in srgb, #213d31 ${Math.round(ratio*88)}%, #f4f6f0)`;}
  return <div className="heatmap-grid" style={{gridTemplateColumns:`minmax(130px,1.2fr) repeat(${columns.length},1fr)`}}>
    <div className="heatmap-head">Source</div>{columns.map(([,name])=><div className="heatmap-head" key={name}>{name}</div>)}
    {rows.flatMap((row)=>[
      <div className="heatmap-source" key={`${label(row.source_domain)}-label`}><strong>{label(row.source_domain)}</strong><small>{number(row.rows).toLocaleString()} rows</small></div>,
      ...columns.map(([key,name])=>{const value=number(row[key]);return <div className="heatmap-cell" key={`${label(row.source_domain)}-${key}`} style={{background:background(value),color:value/max>.48?"#f4f6f0":"#213d31"}} title={`${label(row.source_domain)} ${name}: ${value.toFixed(1)}%`}><strong>{value.toFixed(1)}%</strong></div>})
    ])}
  </div>;
}

export function ReleaseYearBars({ rows }: { rows: { label?: unknown; count?: unknown }[] }) {
  const data=rows.filter((row)=>/^\d{4}$/.test(label(row.label))).map((row)=>({year:Number(row.label),count:number(row.count)})).sort((a,b)=>a.year-b.year);
  if (!data.length) return <div className="table-empty">No release-year values returned.</div>;
  const max=Math.max(1,...data.map((row)=>row.count));
  return <div className="year-bars">{data.map((row)=><div key={row.year} className="year-column"><div className="year-bar-area"><i style={{height:`${Math.max(3,row.count/max*100)}%`}}><span>{row.count}</span></i></div><b>{row.year}</b></div>)}</div>;
}
