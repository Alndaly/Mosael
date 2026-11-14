export type ReservationRow = {
  unit: string;
  amount: string;
};

export const DEFAULT_RESERVATION_ROWS: ReservationRow[] = [{ unit: "image", amount: "1" }];

export function rowsFromCapability(capability: Record<string, unknown>): ReservationRow[] {
  const reservation = capability.reservation;
  if (!reservation || typeof reservation !== "object" || Array.isArray(reservation)) {
    return [...DEFAULT_RESERVATION_ROWS];
  }
  const rows = Object.entries(reservation).map(([unit, amount]) => ({ unit, amount: String(amount) }));
  return rows.length > 0 ? rows : [...DEFAULT_RESERVATION_ROWS];
}

export function reservationFromRows(rows: ReservationRow[]): Record<string, number> {
  const reservation: Record<string, number> = {};
  for (const row of rows) {
    const unit = row.unit.trim();
    const amount = Number(row.amount);
    if (!unit || !Number.isInteger(amount) || amount < 1 || unit in reservation) {
      throw new Error("invalid reservation");
    }
    reservation[unit] = amount;
  }
  if (Object.keys(reservation).length === 0) {
    throw new Error("empty reservation");
  }
  return reservation;
}
