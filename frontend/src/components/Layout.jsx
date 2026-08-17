// Trading dashboard layout:
//   top row : market data | positions | new trade
//   bottom  : trade blotter (full width)
export function Layout({ topLeft, topCenter, topRight, bottom }) {
  return (
    <main className="layout">
      <section className="layout__top">
        <div className="panel">{topLeft}</div>
        <div className="panel">{topCenter}</div>
        <div className="panel">{topRight}</div>
      </section>
      <section className="panel layout__bottom">{bottom}</section>
    </main>
  );
}
