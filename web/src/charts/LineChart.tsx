import { useMemo, useState } from "react";

import { compact, mediumDate, niceTicks, shortDate } from "./format";
import { useMeasure } from "./useMeasure";

export interface LinePoint {
  date: string;
  value: number | null;
}

export interface LineSeries {
  name: string;
  color: string;
  points: LinePoint[];
}

interface Band {
  from: number;
  to: number;
  label: string;
}

interface Props {
  series: LineSeries[];
  height?: number;
  format?: (value: number) => string;
  band?: Band;
  area?: boolean;
  emptyMessage?: string;
}

const M = { top: 14, right: 58, bottom: 26 };
const CHAR_W = 6.2; // 11px tabular digits; keeps ticks from being clipped
const MIN_LEFT = 34;

export default function LineChart({
  series,
  height = 220,
  format = compact,
  band,
  area = false,
  emptyMessage = "No data in this range.",
}: Props) {
  const { ref, width } = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const dates = useMemo(() => {
    const all = new Set<string>();
    for (const s of series) for (const p of s.points) all.add(p.date);
    return [...all].sort();
  }, [series]);

  const lookup = useMemo(
    () => series.map((s) => new Map(s.points.map((p) => [p.date, p.value]))),
    [series],
  );

  const values = series.flatMap((s) => s.points.map((p) => p.value).filter((v): v is number => v != null));

  if (dates.length === 0 || values.length === 0) {
    return (
      <div ref={ref} className="chart">
        <p className="muted">{emptyMessage}</p>
      </div>
    );
  }

  const innerH = height - M.top - M.bottom;

  const tMin = new Date(`${dates[0]}T00:00:00`).getTime();
  const tMax = new Date(`${dates[dates.length - 1]}T00:00:00`).getTime();
  const span = tMax - tMin || 1;

  const dataMin = Math.min(...values, band ? band.from : Infinity);
  const dataMax = Math.max(...values, band ? band.to : -Infinity);
  const pad = (dataMax - dataMin) * 0.12 || 1;
  const yMin = Math.max(0, dataMin - pad);
  const yMax = dataMax + pad;

  const ticks = niceTicks(yMin, yMax, 4);
  const widest = Math.max(...ticks.map((t) => format(t).length));
  const left = Math.max(MIN_LEFT, Math.round(widest * CHAR_W) + 14);
  const innerW = Math.max(width - left - M.right, 10);

  const x = (date: string) =>
    left + ((new Date(`${date}T00:00:00`).getTime() - tMin) / span) * innerW;
  const y = (value: number) => M.top + innerH - ((value - yMin) / (yMax - yMin)) * innerH;

  const pathFor = (index: number) => {
    let d = "";
    let open = false;
    for (const date of dates) {
      const v = lookup[index].get(date);
      if (v == null) {
        open = false;
        continue;
      }
      d += `${open ? "L" : "M"}${x(date).toFixed(2)},${y(v).toFixed(2)}`;
      open = true;
    }
    return d;
  };

  const lastPoint = (index: number): LinePoint | null => {
    const points = series[index].points.filter((p) => p.value != null);
    return points.length ? points[points.length - 1] : null;
  };

  const onMove = (event: React.PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - box.left + left;
    let best = 0;
    let bestDist = Infinity;
    dates.forEach((date, i) => {
      const dist = Math.abs(x(date) - px);
      if (dist < bestDist) {
        bestDist = dist;
        best = i;
      }
    });
    setHover(best);
  };

  const hoverDate = hover != null ? dates[hover] : null;
  const showLegend = series.length >= 2;

  return (
    <div ref={ref} className="chart">
      {showLegend && (
        <div className="legend">
          {series.map((s) => (
            <span className="legend-item" key={s.name}>
              <svg width="14" height="8" aria-hidden="true">
                <line
                  x1="0"
                  y1="4"
                  x2="14"
                  y2="4"
                  stroke={s.color}
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
              {s.name}
            </span>
          ))}
        </div>
      )}

      {width > 0 && (
        <div className="chart-plot">
          <svg width={width} height={height} role="img">
            {band && (
              <>
                <rect
                  x={left}
                  y={y(band.to)}
                  width={innerW}
                  height={Math.max(y(band.from) - y(band.to), 1)}
                  className="viz-band"
                />
                <text x={left + 6} y={y(band.to) - 4} className="viz-axis-text">
                  {band.label}
                </text>
              </>
            )}

            {ticks.map((t) => (
              <g key={t}>
                <line x1={left} y1={y(t)} x2={left + innerW} y2={y(t)} className="viz-grid" />
                <text x={left - 8} y={y(t) + 4} textAnchor="end" className="viz-axis-text">
                  {format(t)}
                </text>
              </g>
            ))}

            <line
              x1={left}
              y1={M.top + innerH}
              x2={left + innerW}
              y2={M.top + innerH}
              className="viz-axis"
            />
            {[dates[0], dates[dates.length - 1]].map((date, i) => (
              <text
                key={date}
                x={x(date)}
                y={height - 8}
                textAnchor={i === 0 ? "start" : "end"}
                className="viz-axis-text"
              >
                {shortDate(date)}
              </text>
            ))}

            {area && series.length === 1 && (
              <path
                d={`${pathFor(0)}L${x(dates[dates.length - 1]).toFixed(2)},${M.top + innerH}L${x(
                  dates[0],
                ).toFixed(2)},${M.top + innerH}Z`}
                fill={series[0].color}
                fillOpacity="0.1"
                stroke="none"
              />
            )}

            {series.map((s, i) => (
              <path
                key={s.name}
                d={pathFor(i)}
                fill="none"
                stroke={s.color}
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ))}

            {hoverDate && (
              <line
                x1={x(hoverDate)}
                y1={M.top}
                x2={x(hoverDate)}
                y2={M.top + innerH}
                className="viz-crosshair"
              />
            )}

            {/* End markers and one direct label per series: labels stay sparing. */}
            {series.map((s, i) => {
              const last = lastPoint(i);
              if (!last || last.value == null) return null;
              return (
                <g key={`end-${s.name}`}>
                  <circle cx={x(last.date)} cy={y(last.value)} r="4" fill={s.color} className="viz-ring" />
                  <text
                    x={x(last.date) + 10}
                    y={y(last.value) + 4}
                    className="viz-end-label"
                  >
                    {format(last.value)}
                  </text>
                </g>
              );
            })}

            {hoverDate &&
              series.map((s, i) => {
                const v = lookup[i].get(hoverDate);
                if (v == null) return null;
                return (
                  <circle
                    key={`hover-${s.name}`}
                    cx={x(hoverDate)}
                    cy={y(v)}
                    r="4"
                    fill={s.color}
                    className="viz-ring"
                  />
                );
              })}

            <rect
              x={left}
              y={M.top}
              width={innerW}
              height={innerH}
              fill="transparent"
              onPointerMove={onMove}
              onPointerLeave={() => setHover(null)}
            />
          </svg>

          {hoverDate && (
            <div
              className="tooltip"
              style={{
                left: Math.min(Math.max(x(hoverDate) + 12, 8), Math.max(width - 150, 8)),
                top: M.top,
              }}
            >
              <div className="tooltip-date">{mediumDate(hoverDate)}</div>
              {series.map((s, i) => {
                const v = lookup[i].get(hoverDate);
                return (
                  <div className="tooltip-row" key={s.name}>
                    <svg width="12" height="8" aria-hidden="true">
                      <line
                        x1="0"
                        y1="4"
                        x2="12"
                        y2="4"
                        stroke={s.color}
                        strokeWidth="2"
                        strokeLinecap="round"
                      />
                    </svg>
                    <span className="tooltip-value">{v == null ? "—" : format(v)}</span>
                    <span className="tooltip-name">{s.name}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
