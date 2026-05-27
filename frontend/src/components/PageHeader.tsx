export function PageHeader({
  title,
  description,
  extra,
}: {
  title: string;
  description?: string;
  extra?: React.ReactNode;
}) {
  return (
    <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && (
          <p className="mt-1.5 max-w-xl text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {extra}
    </header>
  );
}

export default PageHeader;
