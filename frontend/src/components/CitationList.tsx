interface Props {
  citations: string[];
}

export function CitationList({ citations }: Props) {
  if (citations.length === 0) return null;
  return (
    <div className="citation-list">
      <h4>Citations</h4>
      <ul>
        {citations.map((c, i) => (
          <li key={i}>{c}</li>
        ))}
      </ul>
    </div>
  );
}
