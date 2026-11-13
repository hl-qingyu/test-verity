const icons: Record<string, string> = {
  sliders:
    'M3 6h4 M11 6h10 M3 12h10 M17 12h4 M3 18h4 M11 18h10 M7 3h4v6H7z M13 9h4v6h-4z M7 15h4v6H7z',
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  file: 'M5 3h9l5 5v13H5z M14 3v6h5 M8 13h8 M8 17h6',
  spark: 'm12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z',
  list: 'M9 5h12 M9 12h12 M9 19h12 M3 5h1 M3 12h1 M3 19h1',
  check: 'm5 12 4 4L19 6',
  code: 'm8 6-6 6 6 6 m8-12 6 6-6 6 M14 3l-4 18',
  branch: 'M6 3v12a4 4 0 0 0 4 4h8 M6 8h8a4 4 0 0 0 4-4 M3 3h6 M15 19h6 M15 3h6',
  plug: 'M8 3v5 M16 3v5 M6 8h12v3a6 6 0 0 1-12 0z M12 17v4',
  task: 'M5 3h14v18H5z M8 8h8 M8 12h8 M8 16h4',
  settings:
    'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2',
  box: 'm3 7 9-5 9 5v10l-9 5-9-5z M3 7l9 5 9-5 M12 12v10',
  template: 'M4 3h16v18H4z M4 8h16 M10 8v13',
  search: 'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l6 6',
  arrow: 'M4 12h16 m-6-6 6 6-6 6',
  upload: 'M12 16V3 m-5 5 5-5 5 5 M4 16v5h16v-5',
  download: 'M12 3v13 m-5-5 5 5 5-5 M4 17v4h16v-4',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v6l4 2',
  alert: 'm12 3 10 18H2z M12 9v5 M12 17h.01',
  info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 11v6 M12 7h.01',
  plus: 'M12 4v16 M4 12h16',
  edit: 'm4 16 12-12 4 4L8 20H4z M13 7l4 4',
  close: 'm6 6 12 12 M18 6 6 18',
  trash: 'M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12 M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6',
  lock: 'M7 10V7a5 5 0 0 1 10 0v3 M5 10h14v11H5z M12 14v3',
  users:
    'M8 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M2 21v-3a6 6 0 0 1 12 0v3 M17 4a4 4 0 0 1 0 8 M18 15a5 5 0 0 1 4 5',
  github:
    'M9 20c-5 2-5-3-7-3 M16 22v-4c0-1-.3-2-1-2 4-.5 6-2 6-6 0-2-.6-3-2-4 .3-1 .3-3 0-4-2 0-3 1-4 2-2-.5-4-.5-6 0-1-1-2-2-4-2-.5 1-.5 3 0 4-1 1-2 2-2 4 0 4 2 5.5 6 6-1 1-1 2-1 3v3',
  chart: 'M4 3v18h17 M8 16v-4 M13 16V8 M18 16V5',
};
export function Icon({ name }: { name: string }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d={icons[name] || icons.file} />
    </svg>
  );
}
