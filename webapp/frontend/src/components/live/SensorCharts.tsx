import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Eyebrow } from "../ui/primitives";
import type { SensorPoint } from "../../hooks/queries";

function ChartCard({
  eyebrow,
  eyebrowTone,
  title,
  unit,
  color,
  dataKey,
  history,
  decimals,
}: {
  eyebrow: string;
  eyebrowTone?: "cyan";
  title: string;
  unit: string;
  color: string;
  dataKey: "temperature" | "humidity";
  history: SensorPoint[];
  decimals: number;
}) {
  const values = history.map((point) => point[dataKey]);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 0;
  const gradId = `grad-${dataKey}`;

  const rangeLabel = values.length
    ? `${min.toFixed(decimals)}–${max.toFixed(decimals)} ${unit}`
    : "Waiting for data";

  return (
    <article className="glass rounded-2xl p-5">
      <div className="mb-1 flex items-center justify-between">
        <div>
          <Eyebrow tone={eyebrowTone}>{eyebrow}</Eyebrow>
          <h2 className="mt-1 text-[15px] font-semibold text-ink">{title}</h2>
        </div>
        <small className="num text-xs text-muted">{rangeLabel}</small>
      </div>
      <div className="h-[168px] w-full">
        {history.length === 0 ? (
          <div className="grid h-full place-items-center text-xs text-faint">
            Waiting for DHT11 readings…
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={history}
              margin={{ top: 8, right: 6, bottom: 0, left: -18 }}
            >
              <defs>
                <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={0.34} />
                  <stop offset="100%" stopColor={color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid
                stroke="rgba(255,255,255,0.05)"
                vertical={false}
              />
              <XAxis
                dataKey="time"
                type="number"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(value) =>
                  new Intl.DateTimeFormat(undefined, {
                    hour: "2-digit",
                    minute: "2-digit",
                  }).format(new Date(value))
                }
                stroke="#545e6f"
                tick={{ fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                minTickGap={48}
              />
              <YAxis
                domain={[
                  (min: number) => Math.floor(min - 1),
                  (max: number) => Math.ceil(max + 1),
                ]}
                stroke="#545e6f"
                tick={{ fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                width={44}
                tickFormatter={(value) => value.toFixed(decimals)}
              />
              <Tooltip
                contentStyle={{
                  background: "#131826",
                  border: "1px solid #2c3446",
                  borderRadius: 12,
                  fontSize: 12,
                }}
                labelStyle={{ color: "#7b8698" }}
                itemStyle={{ color }}
                labelFormatter={(value) =>
                  new Intl.DateTimeFormat(undefined, {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  }).format(new Date(value as number))
                }
                formatter={(value: number) => [
                  `${value.toFixed(decimals)} ${unit}`,
                  title,
                ]}
              />
              <Area
                type="monotone"
                dataKey={dataKey}
                stroke={color}
                strokeWidth={2}
                fill={`url(#${gradId})`}
                isAnimationActive={false}
                dot={false}
                activeDot={{ r: 3.5, fill: color }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
      <div className="mt-1 flex items-center justify-between text-[11px] text-faint">
        <span>Rolling window</span>
        <span>{unit}</span>
      </div>
    </article>
  );
}

export function SensorCharts({ history }: { history: SensorPoint[] }) {
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <ChartCard
        eyebrow="Environment"
        title="Temperature history"
        unit="°C"
        color="#ff6a2c"
        dataKey="temperature"
        history={history}
        decimals={1}
      />
      <ChartCard
        eyebrow="Environment"
        eyebrowTone="cyan"
        title="Humidity history"
        unit="% RH"
        color="#2ad3c4"
        dataKey="humidity"
        history={history}
        decimals={0}
      />
    </div>
  );
}
