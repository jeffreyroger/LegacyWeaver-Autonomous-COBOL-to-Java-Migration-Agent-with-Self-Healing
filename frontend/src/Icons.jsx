// Small stroke-icon set, ported 1:1 from the original mockup's inline SVGs.

const base = { width: 15, height: 15, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2.2, strokeLinecap: 'round', strokeLinejoin: 'round' }

export function CheckIcon(props) {
  return <svg {...base} {...props}><path d="M20 6 9 17l-5-5" /></svg>
}
export function CritIcon(props) {
  return <svg {...base} strokeWidth={2} {...props}><rect x="3" y="3" width="18" height="18" rx="5" /><path d="m9 9 6 6M15 9l-6 6" strokeLinecap="round" /></svg>
}
export function WarnIcon(props) {
  return <svg {...base} strokeWidth={2} {...props}><path d="M10.3 3.9 1.9 18a2 2 0 0 0 1.7 3h16.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4M12 17h.01" /></svg>
}
export function RunIcon(props) {
  return <svg {...base} strokeWidth={2.2} {...props}><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.9 2.9M15.5 15.5l2.9 2.9M18.4 5.6l-2.9 2.9M8.5 15.5l-2.9 2.9" opacity=".9" /></svg>
}
export function ArrowIcon(props) {
  return <svg {...base} strokeWidth={2.1} {...props}><path d="M5 12h13" /><path d="m13 6 6 6-6 6" /></svg>
}
export function ChevronLeftIcon(props) {
  return <svg {...base} width={13} height={13} {...props}><path d="m14 6-6 6 6 6" /></svg>
}
export function ChevronDownIcon(props) {
  return <svg {...base} width={10} height={10} viewBox="0 0 24 24" fill="currentColor" stroke="none" {...props}><path d="M8 5l10 7-10 7z" /></svg>
}
export function PlusIcon(props) {
  return <svg {...base} strokeWidth={1.8} {...props}><path d="M12 5v14M5 12h14" /></svg>
}
export function TreeIcon(props) {
  return <svg {...base} width={16} height={16} strokeWidth={1.8} {...props}><path d="M21 8v8a2 2 0 0 1-1 1.73l-7 4a2 2 0 0 1-2 0l-7-4A2 2 0 0 1 3 16V8a2 2 0 0 1 1-1.73l7-4a2 2 0 0 1 2 0l7 4A2 2 0 0 1 21 8z" /><path d="m3.3 7 8.7 5 8.7-5M12 22V12" /></svg>
}
export function GaugeIcon(props) {
  return <svg {...base} width={16} height={16} strokeWidth={1.8} {...props}><path d="M3 3v16a2 2 0 0 0 2 2h16" /><path d="m7 14 3.5-3.5 3 3L20 7" /></svg>
}
export function GearIcon(props) {
  return <svg {...base} width={16} height={16} strokeWidth={1.8} {...props}><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" /><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 9 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z" /></svg>
}
export function SearchIcon(props) {
  return <svg {...base} width={14} height={14} strokeWidth={2} {...props}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
}
export function SunIcon(props) {
  return <svg {...base} width={13} height={13} strokeWidth={2} {...props}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
}
export function MoonIcon(props) {
  return <svg {...base} width={13} height={13} strokeWidth={2} {...props}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
}
export function ShieldIcon(props) {
  return <svg {...base} width={16} height={16} {...props}><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" /><path d="m9 12 2 2 4-4" /></svg>
}
export function ShieldWarnIcon(props) {
  return <svg {...base} width={16} height={16} {...props}><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" /><path d="M12 8v5M12 16h.01" /></svg>
}
