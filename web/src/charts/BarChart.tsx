import { useState } from "react";

import { compact, niceTicks } from "./format";
import { useMeasure } from "./useMeasure";

export interface Bar {
  label: string;
  value: number;
  detail?: string;
}

interface Props {
  bars: Bar[];
  color: string;
  format?: (value: number) => string;
  emptyMessage?: string;
}

const M = { top: 8, right: 56, bottom: 24, left: 96 };
const BAND = 28; // keeps every hit target >= 24px
const MAX_THICKNESS = 24;
const GAP = 2; // surface gap between adjacent bars
const RADIUS = 4; // rounded data-end; the baseline end stays square

/** Bar with a rounded end at the value side only, square against the baseline. */
function barPath(x0: number, x1: number, top: number, thickness: number): string {
  const r = Math.min(RADIUS, Math.max(x1 - x0, 0));
  const bottom = top + thickness;
  if (r <= 0) return `M${x0},${top}H${x0}V${bottom}H${x0}Z`;
  return [
    `M${x0},${top}`,
    `H${x1 - r}`,
    `A${r},${r} 0 0 1 ${x1},${top + r}`,
    `V${bottom - r}`,
    `A${r},${r} 0 0 1 ${x1 - r},${bottom}`,
    `H${x0}`,
    "Z",
  ].join("");
}

export default function BarChart({
  bars,
  color,
  format = compact,
  emptyMessage = "No data in this range.",
}: Props) {
  const { ref, width } = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  if (bars.length === 0) {
    return (
      <div ref={ref} className="chart">
        <p className="muted">{emptyMessage}</p>
      </div>
    );
  }

  const height = M.top + bars.length * BAND + M.bottom;
  const innerW = Math.max(width - M.left - M.right, 10);
  const max = Math.max(...bars.map((b) => b.value), 1);
  const ticks = niceTicks(0, max, 3);
  const x = (value: number) => M.left + (value / max) * innerW;
  const thickness = Math.min(MAX_THICKNESS, BAND - GAP);

  return (
    <div ref={ref} className="chart">
      {width > 0 && (
        <div className="chart-plot">
          <svg width={width} height={height} role="img">
            {ticks.map((t) => (
              <g key={t}>
                <line x1={x(t)} y1={M.top} x2={x(t)} y2={M.top + bars.length * BAND} className="viz-grid" />
                <text x={x(t)} y={height - 8} textAnchor="middle" className="viz-axis-text">
                  {format(t)}
                </text>
              </g>
            ))}

            {bars.map((bar, i) => {
              const top = M.top + i * BAND + (BAND - thickness) / 2;
              const end = x(bar.value);
              return (
                <g
                  key={bar.label}
                  onPointerEnter={() => setHover(i)}
                  onPointerLeave={() => setHover(null)}
                  className={hover === i ? "viz-bar hovered" : "viz-bar"}
                >
                  <text x={M.left - 10} y={top + thickness / 2 + 4} textAnchor="end" className="viz-axis-text">
                    {bar.label}
                  </text>
                  <path d={barPath(M.left, end, top, thickness)} fill={color} />
                  <text x={end + 8} y={top + thickness / 2 + 4} className="viz-end-label">
                    {format(bar.value)}
                  </text>
                  {/* Hit target spans the whole band, not just the painted bar. */}
                  <rect
                    x={M.left}
                    y={M.top + i * BAND}
                    width={innerW + M.right}
                    height={BAND}
                    fill="transparent"
                  />
                </g>
              );
            })}

            <line
              x1={M.left}
              y1={M.top}
              x2={M.left}
              y2={M.top + bars.length * BAND}
              className="viz-axis"
            />
          </svg>

          {hover != null && (
            <div
              className="tooltip"
              style={{ left: Math.min(x(bars[hover].value) + 12, Math.max(width - 160, 8)), top: M.top + hover * BAND }}
            >
              <div className="tooltip-row">
                <span className="tooltip-value">{format(bars[hover].value)}</span>
                <span className="tooltip-name">{bars[hover].label}</span>
              </div>
              {bars[hover].detail && <div className="tooltip-date">{bars[hover].detail}</div>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
