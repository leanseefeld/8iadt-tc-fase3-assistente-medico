/** Médicos mock: credenciais só para demo (sem servidor de auth). */

export interface MockDoctor {
  id: string;
  /** Login fake (sem validação de e-mail). */
  username: string;
  /** Senha em texto — protótipo local apenas. */
  password: string;
  name: string;
  crm: string;
  uf: string;
}

export const MOCK_DOCTORS: MockDoctor[] = [
  {
    id: 'dr-ana',
    username: 'ana.souza',
    password: 'ana123',
    name: 'Dra. Ana Souza',
    crm: '123456',
    uf: 'SP',
  },
  {
    id: 'dr-bruno',
    username: 'bruno.lima',
    password: 'bruno123',
    name: 'Dr. Bruno Lima',
    crm: '654321',
    uf: 'RJ',
  },
  {
    id: 'dr-carla',
    username: 'carla.mendes',
    password: 'carla123',
    name: 'Dra. Carla Mendes',
    crm: '789012',
    uf: 'MG',
  },
];
