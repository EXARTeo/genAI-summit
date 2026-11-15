// Backend paths of the findings register (behind /api; backend `router/register.py`).
const enc = encodeURIComponent;

export const registerApi = {
  list: (systemId: string) => `/v1/systems/${enc(systemId)}/register`,
  item: (systemId: string, obligationId: string) =>
    `/v1/systems/${enc(systemId)}/register/${enc(obligationId)}`,
  close: (systemId: string, obligationId: string) =>
    `/v1/systems/${enc(systemId)}/register/${enc(obligationId)}/close`,
  reopen: (systemId: string, obligationId: string) =>
    `/v1/systems/${enc(systemId)}/register/${enc(obligationId)}/reopen`,
};
