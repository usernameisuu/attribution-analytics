import type { Analysis } from './api';

export function canApplySnapshot(current:Analysis|null, incoming:Analysis, expectedRevision:string|undefined):boolean {
  return Boolean(current && current.id === incoming.id && expectedRevision && current.report_revision === expectedRevision);
}
