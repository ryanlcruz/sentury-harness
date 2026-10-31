class Elemento {
  constructor() {
    this.children = []; this.seletores = new Map(); this.atributos = new Map();
    this.style = {setProperty(){},removeProperty(){}};
    const classes = new Set();
    this.classList = {add:n=>classes.add(n),remove:n=>classes.delete(n),
      toggle(n,valor){if(valor) classes.add(n); else classes.delete(n)},contains:n=>classes.has(n)};
  }
  set innerHTML(texto) {this.markup=texto; this.seletores.clear()}
  get innerHTML() {return this.markup || ''}
  setAttribute(n,v) {this.atributos.set(n,v)}
  getAttribute(n) {return this.atributos.get(n)}
  querySelector(chave) {
    if (!this.seletores.has(chave)) this.seletores.set(chave,new Elemento());
    return this.seletores.get(chave);
  }
  appendChild(el) {el.remove(); this.children.push(el); el.parentNode=this; return el}
  insertBefore(el,proximo) {
    el.remove(); const i=proximo ? this.children.indexOf(proximo) : this.children.length;
    if(i<0) throw Error('o objeto está em outra camada');
    this.children.splice(i,0,el); el.parentNode=this;
  }
  remove() {if(this.parentNode) {const lista=this.parentNode.children; lista.splice(lista.indexOf(this),1); this.parentNode=null}}
  replaceChildren() {this.children.forEach(c=>{c.parentNode=null});this.children=[];this.seletores.clear()}
  addEventListener() {} removeEventListener() {}
  getComputedTextLength() {return 42}
  getBoundingClientRect() {return {width:540,height:450}}
}

module.exports = function preparar() {
  let agora=0, id=0;
  const timers=new Map(), modelos=new Set(), montagens=[];
  const motor={canvas:new Elemento(),montar(n){modelos.add(n);montagens.push(n)},posar(){},
    posicionar(){},destacar(){},assentos(){},desenhar(){},resolucao(){},medicao(){return {chamadas:1,triangulos:1}},
    retrato(){return ''},remover(n){modelos.delete(n)},destruir(){modelos.clear()}};
  global.performance={now:()=>agora};
  global.document={hidden:false,createElement:()=>new Elemento(),createElementNS:()=>new Elemento(),
    addEventListener(){},removeEventListener(){}};
  global.window={matchMedia:()=>({matches:false}),addEventListener(){},removeEventListener(){},
    setTimeout(fn,ms){timers.set(++id,{fn,em:agora+ms});return id},clearTimeout(n){timers.delete(n)},
    setInterval(){return ++id},clearInterval(){}};
  global.requestAnimationFrame=()=>++id; global.cancelAnimationFrame=()=>{};
  global.CSS={escape:t=>t};
  return {host:new Elemento(),motor,modelos,montagens,
    async passar(sala,segundos,conferir=()=>{}) {
      for(let i=0;i<segundos*30;i++) {
        agora+=1000/30;
        for(const [n,t] of [...timers]) if(t.em<=agora) {timers.delete(n);t.fn()}
        sala.quadro(agora); conferir();
        await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
      }
    },silenciarVoltas(sala) {sala.darUmaVolta=()=>{}; sala.olharEmVolta=()=>{}; sala.piscar=()=>{}}
  };
};
