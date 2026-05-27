export function StudioPanel({
  header,
  extra,
  children,
  className = "",
  bodyClassName = "",
}: {
  header?: React.ReactNode;
  extra?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`studio-panel ${className}`}>
      {header != null && (
        <header className="studio-panel-header">
          <span>{header}</span>
          {extra}
        </header>
      )}
      <div className={`studio-panel-body ${bodyClassName}`}>{children}</div>
    </section>
  );
}
