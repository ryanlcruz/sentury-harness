// O pacote não publica tipos para o módulo de cada ícone; o bloco vivo só lê os traços.
declare module 'lucide-react/dist/esm/icons/*' {
  export const __iconData: {
    name: string;
    size: number;
    node: [string, Record<string, string>][];
  };
}
