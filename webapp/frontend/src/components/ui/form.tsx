import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
} from "react";
import { cx } from "./primitives";
import type { Model } from "../../lib/types";

export const controlClass =
  "w-full rounded-xl border border-line bg-base/70 px-3.5 py-2.5 text-sm text-ink outline-none transition focus:border-brand/60 focus:ring-2 focus:ring-brand/20 disabled:opacity-50 disabled:cursor-not-allowed";

export function Field({
  label,
  htmlFor,
  children,
  className,
}: {
  label: string;
  htmlFor?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("flex flex-col gap-1.5", className)}>
      <label
        htmlFor={htmlFor}
        className="text-[11px] font-semibold uppercase tracking-wider text-faint"
      >
        {label}
      </label>
      {children}
    </div>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(controlClass, props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cx(controlClass, "appearance-none pr-9", props.className)}
      style={{
        backgroundImage:
          "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%237b8698' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")",
        backgroundRepeat: "no-repeat",
        backgroundPosition: "right 0.75rem center",
      }}
    />
  );
}

export function ModelSelect({
  models,
  value,
  onChange,
  id,
}: {
  models: Model[];
  value: string;
  onChange: (value: string) => void;
  id?: string;
}) {
  return (
    <Select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
      {models.length === 0 && <option>Loading models…</option>}
      {models.map((model) => (
        <option key={model.id} value={model.id} disabled={!model.cached}>
          {model.name}
          {model.cached ? "" : " · download first"}
        </option>
      ))}
    </Select>
  );
}
