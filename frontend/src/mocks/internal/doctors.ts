/** Médicos mock para login fake (seletor na barra superior). */

export interface MockDoctor {
  id: string;
  name: string;
  crm: string;
  uf: string;
}

export const MOCK_DOCTORS: MockDoctor[] = [
  { id: 'dr-ana', name: 'Dra. Ana Souza', crm: '123456', uf: 'SP' },
  { id: 'dr-bruno', name: 'Dr. Bruno Lima', crm: '654321', uf: 'RJ' },
  { id: 'dr-carla', name: 'Dra. Carla Mendes', crm: '789012', uf: 'MG' },
];
