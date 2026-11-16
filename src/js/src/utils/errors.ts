/** The message of whatever was thrown (`catch (e)` gives `unknown`). */
export const messageOf = (thrown: unknown): string => (thrown instanceof Error ? thrown.message : String(thrown))
