/**
 * Cadastro demo (concentração e forma farmacêutica) para o formulário de prescrição.
 * Não substitui normas técnicas; apenas simula listas curtas no protótipo.
 */

export const PRESCRIPTION_CUSTOM_KEY = '__custom__';

export interface PrescriptionPresetOption {
  id: string;
  label: string;
}

/** Concentrações típicas (exemplos para demo). */
export const PRESCRIPTION_CONCENTRATION_PRESETS: PrescriptionPresetOption[] = [
  { id: '5mg', label: '5 mg' },
  { id: '10mg', label: '10 mg' },
  { id: '25mg', label: '25 mg' },
  { id: '50mg', label: '50 mg' },
  { id: '100mg', label: '100 mg' },
  { id: '500mg', label: '500 mg' },
  { id: '5mg-5ml', label: '5 mg / 5 ml' },
  { id: '50mg-ml', label: '50 mg/ml' },
  { id: '400mg-5ml', label: '400 mg/5 ml' },
];

/** Formas farmacêuticas comuns (exemplos para demo). */
export const PRESCRIPTION_FORM_PRESETS: PrescriptionPresetOption[] = [
  { id: 'comp', label: 'Comprimido' },
  { id: 'cap', label: 'Cápsula' },
  { id: 'drg', label: 'Drágea' },
  { id: 'xar', label: 'Xarope' },
  { id: 'sol-oral', label: 'Solução oral' },
  { id: 'gotas', label: 'Solução oral (gotas)' },
  { id: 'inj-amp', label: 'Injetável (ampola)' },
  { id: 'inj-fr', label: 'Injetável (frasco-ampola)' },
  { id: 'pom', label: 'Pomada' },
  { id: 'cr', label: 'Creme' },
  { id: 'sup', label: 'Supositório' },
];
