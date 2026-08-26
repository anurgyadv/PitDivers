import { Boxes, Radio, Images, PackageOpen, type LucideIcon } from "lucide-react";

export type Tab = "live" | "captures" | "reconstructions" | "models";

export interface NavMeta {
  id: Tab;
  label: string;
  icon: LucideIcon;
  eyebrow: string;
  title: string;
}

export const NAV: NavMeta[] = [
  {
    id: "live",
    label: "Live",
    icon: Radio,
    eyebrow: "Operations",
    title: "Live inspection",
  },
  {
    id: "captures",
    label: "Captures",
    icon: Images,
    eyebrow: "Evidence",
    title: "Captured photos",
  },
  {
    id: "reconstructions",
    label: "3D Models",
    icon: Boxes,
    eyebrow: "Spatial output",
    title: "3D reconstructions",
  },
  {
    id: "models",
    label: "DA3 Models",
    icon: PackageOpen,
    eyebrow: "Model library",
    title: "Depth Anything 3 models",
  },
];
