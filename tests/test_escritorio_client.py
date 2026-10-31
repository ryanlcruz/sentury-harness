import shutil
import subprocess
import json
from pathlib import Path

import pytest


CLIENT = Path('sentury/client')
CARREGADOR = r"""
const fs = require('fs'), path = require('path'), ts = require('typescript');
const assert = require('node:assert/strict'), THREE = require('three');
const cache = new Map(), dublês = new Map();
function carregar(nome) {
  const arquivo = path.resolve(nome);
  if (dublês.has(arquivo)) return dublês.get(arquivo);
  if (cache.has(arquivo)) return cache.get(arquivo).exports;
  const modulo = {exports: {}}; cache.set(arquivo, modulo);
  const codigo = ts.transpileModule(fs.readFileSync(arquivo, 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}
  }).outputText;
  const local = nome => nome.startsWith('.') ? carregar(path.resolve(path.dirname(arquivo), nome + '.ts')) : require(nome);
  new Function('require', 'exports', 'module', codigo)(local, modulo.exports, modulo);
  return modulo.exports;
}
const raiz = 'src/features/residentes/escritorio/';
"""


def rodar(script):
    node = shutil.which('node')
    if not node or not (CLIENT / 'node_modules/three').exists():
        pytest.skip('o teste precisa das dependências locais do client')
    if 'async function testar()' in script:
        script = ('let finalizado=false; process.on("beforeExit",()=>{if(!finalizado) '
                  '{console.error("o fluxo ficou preso");process.exitCode=1}});' + script)
        script = script.replace('testar().catch(', 'testar().then(()=>{finalizado=true}).catch(')
    resultado = subprocess.run([node, '-e', CARREGADOR + script], cwd=CLIENT,
                               capture_output=True, text=True, timeout=60)
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    return resultado.stdout


def test_camera_e_svg_compartilham_posicao_e_altura():
    rodar(r"""
    const {iso} = carregar(raiz + 'iso.ts');
    const {cameraDaSala, QUADRO_DA_SALA: q} = carregar(raiz + 'projecao3d.ts');
    const cam = cameraDaSala();
    for (const x of [0, 1.75, 6.3, 12]) for (const y of [0, 3.25, 5.7, 10]) for (const z of [0, .45, 1.5]) {
      const p = new THREE.Vector3(x, z, y).project(cam), s = iso(x, y, z);
      assert.ok(Math.abs(q.x + (p.x + 1) * q.largura / 2 - s[0]) < .00001);
      assert.ok(Math.abs(q.y + (1 - p.y) * q.altura / 2 - s[1]) < .00001);
    }
    """)


def test_medicao_separa_pausa_de_atraso_real_e_preserva_picos():
    rodar(r"""
    const {MedidorDaSala}=carregar(raiz+'medicao.ts');
    const medidor=new MedidorDaSala();
    const quadro=(intervalo=1000/30,ms=2)=>medidor.receber({intervalo,ms,chamadas:223,triangulos:96652});
    let a;
    for(let i=0;i<30;i++) a=quadro();
    assert.ok(Math.abs(a.fps-30)<.001); assert.equal(a.cpu,2);
    assert.ok(Math.abs(a.intervalo95-1000/30)<.001); assert.equal(a.atrasados,0);
    for(let i=0;i<10;i++) assert.equal(quadro(),null);
    medidor.reiniciar();
    for(let i=0;i<29;i++) assert.equal(quadro(),null);
    a=quadro(); assert.ok(Math.abs(a.fps-30)<.001);
    for(let i=0;i<25;i++) a=quadro(40);
    assert.equal(a.fps,25); assert.equal(a.intervalo95,40);
    for(let i=0;i<15;i++) assert.equal(quadro(),null);
    a=quadro(500,8);
    assert.ok(Math.abs(a.fps-16)<.001); assert.equal(a.intervaloMax,500);
    assert.equal(a.intervalo95,500); assert.equal(a.atrasados,1);
    assert.equal(a.cpuMax,8); assert.equal(a.cpu,38/16);
    assert.equal(a.chamadas,223); assert.equal(a.triangulos,96652);
    a=quadro(2000); assert.equal(a.intervaloMax,2000); assert.equal(a.fps,.5);
    """)


def test_motor_nao_conta_tempo_oculto_no_intervalo_da_retomada():
    rodar(r"""
    const dom=require('../../tests/fixtures/escritorio_dom.cjs')();
    dublês.set(path.resolve(raiz+'coruja3d.ts'),{criar3D:()=>dom.motor});
    const {Escritorio}=carregar(raiz+'escritorio.ts');
    const {MedidorDaSala}=carregar(raiz+'medicao.ts');
    const medidor=new MedidorDaSala(), atividades=[], amostras=[], intervalos=[];
    const sala=new Escritorio(dom.host,{aoSelecionar(){},aoAtividade(a){atividades.push(a);medidor.reiniciar()},
      aoQuadro(m){intervalos.push(m.intervalo);const a=medidor.receber(m);if(a)amostras.push(a)}});
    dom.silenciarVoltas(sala);
    async function testar() {
      await dom.passar(sala,.5); const n=intervalos.length;
      document.hidden=true; sala.atualizarAtividade(); await dom.passar(sala,10);
      assert.equal(intervalos.length,n);
      document.hidden=false; sala.atualizarAtividade(); await dom.passar(sala,1.1);
      assert.deepEqual(atividades,[true,false,true]);
      assert.ok(intervalos.every(i=>i<34));
      assert.equal(amostras.length,1); assert.ok(Math.abs(amostras[0].fps-30)<.001);
      sala.naTela=false; sala.atualizarAtividade(); await dom.passar(sala,5);
      sala.naTela=true; sala.atualizarAtividade(); await dom.passar(sala,1.1);
      assert.deepEqual(atividades,[true,false,true,false,true]);
      assert.equal(amostras.length,2); assert.ok(Math.abs(amostras[1].fps-30)<.001);
      sala.destruir();
    }
    testar().catch(e=>{console.error(e);process.exitCode=1});
    """)


def test_sala_parada_desenha_menos_e_volta_ao_ritmo_cheio_ao_tocar():
    """Parada, a sala só respira e pisca: 8 quadros/s bastam. Mouse, seleção ou
    fala voltam a 30 no mesmo instante."""
    rodar(r"""
    const dom=require('../../tests/fixtures/escritorio_dom.cjs')();
    dublês.set(path.resolve(raiz+'coruja3d.ts'),{criar3D:()=>dom.motor});
    const {Escritorio}=carregar(raiz+'escritorio.ts');
    const medidas=[];
    const sala=new Escritorio(dom.host,{aoSelecionar(){},aoQuadro(m){medidas.push(m)}});
    dom.silenciarVoltas(sala);
    async function testar() {
      await dom.passar(sala,3);
      medidas.length=0; await dom.passar(sala,2);
      assert.ok(medidas.length>0 && medidas.length<=17, String(medidas.length));
      assert.ok(medidas.every(m=>m.esperado===125));
      sala.selecionar(null); medidas.length=0; await dom.passar(sala,.5);
      assert.ok(medidas.length>=14, String(medidas.length));
      assert.ok(medidas.every(m=>Math.abs(m.esperado-1000/30)<.001));
      sala.destruir();
    }
    testar().catch(e=>{console.error(e);process.exitCode=1});
    """)


def test_montagem_progressiva_cede_quadros_e_espera_os_shaders():
    rodar(r"""
    const dom=require('../../tests/fixtures/escritorio_dom.cjs')();
    const compilacoes=[], progresso=[]; let desenhos=0;
    dom.motor.preparar=()=>new Promise(resolve=>compilacoes.push(resolve));
    dom.motor.desenhar=()=>desenhos++;
    dublês.set(path.resolve(raiz+'coruja3d.ts'),{criar3D:()=>dom.motor});
    const {Escritorio}=carregar(raiz+'escritorio.ts');
    const sala=new Escritorio(dom.host,{aoSelecionar(){},progressivo:true,aoPreparacao:n=>progresso.push(n)});
    dom.silenciarVoltas(sala);
    const lista=['atlas','iris','forge','nox'].map(nome=>({nome,rotulo:nome,familia:'geral',pose:'parado',
      cores:{penas:'#123456',asas:'#234567',barriga:'#345678',olho:'#456789'},acessorios:{}}));
    async function testar() {
      sala.sincronizar(lista); assert.equal(dom.montagens.length,0);
      await dom.passar(sala,.1); assert.deepEqual(dom.montagens,['atlas']);
      assert.equal(desenhos,0); assert.equal(compilacoes.length,1);
      compilacoes.shift()(); await dom.passar(sala,.1);
      assert.deepEqual(dom.montagens,['atlas','iris']); assert.equal(compilacoes.length,1);
      // Sai antes de sua vez; não constrói nem compila o modelo removido.
      sala.sincronizar(lista.filter(r=>r.nome!=='forge'));
      compilacoes.shift()(); await dom.passar(sala,.1);
      assert.deepEqual(dom.montagens,['atlas','iris','nox']);
      compilacoes.shift()(); await dom.passar(sala,.1);
      assert.ok(desenhos>0); assert.equal(progresso.at(-1),0);
      sala.sincronizar(lista.filter(r=>r.nome==='atlas').map(r=>({...r,acessorios:{cabeca:'gorro'}})));
      await dom.passar(sala,.1); assert.equal(compilacoes.length,1);
      const n=progresso.length; sala.destruir(); compilacoes.shift()();
      await dom.passar(sala,.1); assert.equal(progresso.length,n); assert.equal(dom.modelos.size,0);
    }
    testar().catch(e=>{console.error(e);process.exitCode=1});
    """)


def test_reuniao_muda_oculta_sem_repetir_gestos_ao_voltar():
    rodar(r"""
    const dom=require('../../tests/fixtures/escritorio_dom.cjs')();
    let desenhos=0; dom.motor.desenhar=()=>desenhos++;
    dublês.set(path.resolve(raiz+'coruja3d.ts'),{criar3D:()=>dom.motor});
    const {Escritorio}=carregar(raiz+'escritorio.ts'),{EventosDaSala}=carregar(raiz+'eventosDaSala.ts');
    const sala=new Escritorio(dom.host,{aoSelecionar(){}}), trilha=new EventosDaSala();
    dom.silenciarVoltas(sala);
    const lista=['atlas','iris','forge'].map(nome=>({nome,rotulo:nome,familia:'geral',pose:'parado',
      cores:{penas:'#123456',asas:'#234567',barriga:'#345678',olho:'#456789'},acessorios:{}}));
    sala.sincronizar(lista);
    let em=0;
    const evento=(tipo,participantes,assunto='a')=>({tipo,participantes,assunto,em:++em,agente:'pessoa',
      tarefa:'',origem:'',texto:'',para:''});
    const receber=(e)=>trilha.receber([e],true,sala,()=>({fala:'fala antiga'}));
    async function testar() {
      sala.pedidoChegou('atlas'); sala.falar('atlas','balão antigo');
      await dom.passar(sala,.1);
      sala.naTela=false; sala.atualizarAtividade(); const n=desenhos;
      receber(evento('mesa_aberta',['atlas','iris']));
      receber(evento('mesa_entrou',['atlas','iris','forge']));
      for(const o of sala.corujas.values()) {assert.ok(o.naMesa);assert.equal(o.postoAtual,o.naMesa);assert.equal(o.caminho.length,0)}
      receber(evento('mesa_aberta',['iris'],'b')); receber(evento('mesa_fechada',[]));
      assert.equal(sala.corujas.get('atlas').naMesa,null);assert.ok(sala.corujas.get('iris').naMesa);
      await dom.passar(sala,10);assert.equal(desenhos,n);
      sala.naTela=true;sala.atualizarAtividade();await dom.passar(sala,1);
      for(const o of sala.corujas.values()) {assert.equal(o.caminho.length,0);assert.equal(o.balao,null);assert.equal(o.ocupado,0)}
      sala.naTela=false;sala.atualizarAtividade();receber(evento('mesa_fechada',[],'b'));
      for(const o of sala.corujas.values()) {assert.equal(o.naMesa,null);assert.equal(o.postoAtual,o.posto)}
      sala.destruir();
    }
    testar().catch(e=>{console.error(e);process.exitCode=1});
    """)


def test_retomada_pede_estado_atual_sem_sobrepor_buscas():
    rodar(r"""
    const {ConsultaDaSala}=carregar(raiz+'consultaDaSala.ts');
    const pedidos=[], estados=[], recebidos=[], erros=[];let reconciliacoes=0;
    const consulta=new ConsultaDaSala({
      eventos:()=>new Promise((resolve,reject)=>pedidos.push({resolve,reject})),
      estado:()=>new Promise(resolve=>estados.push(resolve)),
    },{eventos:(e,a)=>recebidos.push([e,a]),estado:e=>recebidos.push(e),
      reconciliar:()=>reconciliacoes++,erro:e=>erros.push(e)});
    const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve()};
    async function testar() {
      const inicial=consulta.buscar();consulta.retomar();consulta.retomar();
      assert.equal(pedidos.length,1);assert.equal(estados.length,1);
      pedidos[0].resolve(['antigo']);estados[0]('antigo');await inicial;await flush();
      assert.deepEqual(recebidos,[]);assert.equal(pedidos.length,2);assert.equal(estados.length,2);
      pedidos[1].resolve(['atual']);estados[1]('atual');await flush();
      assert.deepEqual(recebidos,[[['atual'],false],'atual']);assert.equal(reconciliacoes,2);
      const seguinte=consulta.buscar();assert.equal(estados.length,2);
      pedidos[2].resolve(['novo']);await seguinte;
      assert.deepEqual(recebidos.at(-1),[['novo'],true]);
      consulta.retomar();pedidos[3].reject(Error('a HQ caiu'));estados[2]('indisponível');await flush();
      assert.equal(erros.at(-1),'a HQ caiu');
      const retry=consulta.buscar();assert.equal(estados.length,4);
      pedidos[4].resolve([]);estados[3]('recuperado');await retry;
      assert.equal(recebidos.at(-1),'recuperado');assert.equal(erros.at(-1),'');
      consulta.retomar();const total=recebidos.length;consulta.parar();
      pedidos[5].resolve(['tardio']);estados[4]('tardio');await flush();
      assert.equal(recebidos.length,total);await consulta.buscar();assert.equal(pedidos.length,6);
    }
    testar().catch(e=>{console.error(e);process.exitCode=1});
    """)


def test_retrato_da_mesa_restaura_assunto_fora_do_feed_do_dia():
    rodar(r"""
    const {EventosDaSala}=carregar(raiz+'eventosDaSala.ts'),trilha=new EventosDaSala(),lugares=[];
    const sala={ativa:()=>true,reconciliarMesa:n=>lugares.push(n),
      falar(){throw Error('não repete fala')},pedidoChegou(){throw Error('não repete envelope')},
      sentarNaMesa(){throw Error('não repete caminhada')},levantarDaMesa(){throw Error('não repete caminhada')}};
    trilha.restaurarMesas([{id:'ontem',estado:'aberto',participantes:['atlas','pessoa','iris']},
      {id:'outro',estado:'aberto',participantes:['iris']},{id:'fechado',estado:'fechado',participantes:['forge']}],sala);
    assert.deepEqual(lugares.at(-1),['atlas','iris']);
    trilha.restaurarMesas([{id:'ontem',estado:'aberto',participantes:['atlas','forge']}],sala);
    assert.deepEqual(lugares.at(-1),['atlas','forge']);
    trilha.restaurarMesas([],sala);assert.deepEqual(lugares.at(-1),[]);
    """)


def test_camadas_de_moveis_sao_ordenadas_sem_misturar_os_pais():
    rodar(r"""
    dublês.set(path.resolve(raiz+'coruja3d.ts'), {criar3D(){return null}});
    const {Escritorio} = carregar(raiz+'escritorio.ts');
    const camada = () => ({filhos:[],insertBefore(g,proximo) {
      assert.ok(!proximo || proximo.parentNode===this);
      const i = proximo ? this.filhos.indexOf(proximo) : this.filhos.length;
      this.filhos.splice(i,0,g); g.parentNode=this;
    }});
    global.document = {createElementNS(){return {innerHTML:'',parentNode:null}}};
    const sala = Object.create(Escritorio.prototype);
    sala.moveis=camada(); sala.frente=camada(); sala.objetos=[];
    sala.addObjeto('mesa',12); sala.addObjeto('vaso',20,true);
    sala.addObjeto('cadeira',11); sala.addObjeto('luminaria',13,true);
    assert.deepEqual(sala.moveis.filhos.map(g=>g.innerHTML),['cadeira','mesa']);
    assert.deepEqual(sala.frente.filhos.map(g=>g.innerHTML),['luminaria','vaso']);
    const fonte=fs.readFileSync(raiz+'escritorio.ts','utf8');
    assert.ok(fonte.includes('<g class="esc-dinamico"></g><g class="esc-frente"></g><g class="esc-sobreposto"></g>'));
    const {ESTILO_DO_ESCRITORIO:css}=carregar(raiz+'estilo.ts');
    assert.ok(css.includes('100dvh - 16rem'));
    assert.ok(css.includes('width: min(100%, calc(var(--esc-altura) * var(--esc-proporcao, 1.2)))'));
    """)


def test_sala_reserva_o_quadro_sem_depender_do_tamanho_das_camadas():
    rodar(r"""
    const {ESTILO_DO_ESCRITORIO:css,QUADRO_DO_ESCRITORIO:quadro}=carregar(raiz+'estilo.ts');
    assert.equal(quadro.position,'relative'); assert.equal(quadro.aspectRatio,'1.2');
    assert.equal(quadro.overflow,'hidden'); assert.equal(quadro.transform,'translateZ(0)');
    for(const arquivo of ['src/dev/InterfaceAtlas.tsx','src/dev/EscritorioAtlas.tsx',raiz+'EscritorioView.tsx'])
      assert.ok(fs.readFileSync(arquivo,'utf8').includes('style={QUADRO_DO_ESCRITORIO}'));
    const regras = Object.fromEntries([...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .map(m=>[m[1].trim(),m[2]]));
    const raizCSS = regras['.esc-raiz'];
    assert.match(raizCSS,/aspect-ratio:\s*var\(--esc-proporcao,\s*1\.2\)/);
    assert.match(raizCSS,/contain:\s*layout paint/);
    assert.match(raizCSS,/position:\s*relative/);
    assert.match(raizCSS,/transform:\s*translateZ\(0\)/);
    assert.match(raizCSS,/overflow:\s*hidden/);
    const camadas = regras['.esc-raiz > svg, .esc-raiz > .esc-canvas3d'];
    for(const regra of [/position:\s*absolute/,/inset:\s*0/,/width:\s*100%/,
                        /height:\s*100%/,/margin:\s*0/]) assert.match(camadas,regra);
    assert.ok(!css.includes('height: auto'));
    """)


def test_router_fica_na_parede_com_folga_e_passagem_sem_planta():
    rodar(r"""
    const {RACK,rackDoRouter}=carregar(raiz+'cenario.ts');
    assert.equal(RACK.y,0);
    assert.ok(RACK.x-8.3>=.13 && 9.3-(RACK.x+RACK.w)>=.13);
    assert.ok(rackDoRouter([]).length>0);
    const {rota}=carregar(raiz+'caminhos.ts');
    const destino={x:11,y:3.8};
    assert.deepEqual(rota({x:11,y:1.5},destino),[destino]);
    for(const arquivo of ['escritorio.ts','coruja3d.ts','caminhos.ts']) {
      const fonte=fs.readFileSync(raiz+arquivo,'utf8');
      assert.ok(!fonte.includes('PLANTA_DO_PORTAL'));
      assert.ok(!fonte.includes("'espada'"));
    }
    for(const [de,ate] of [[{x:8.3,y:1.6},{x:10.4,y:1.9}], [{x:11,y:1.5},{x:11,y:3.8}]]) {
      const caminho=rota(de,ate); assert.ok(caminho.length);
      let anterior=de;
      for(const ponto of caminho) {
        for(let i=0;i<=100;i++) {
          const x=anterior.x+(ponto.x-anterior.x)*i/100, y=anterior.y+(ponto.y-anterior.y)*i/100;
          assert.ok(!(x>RACK.x && x<RACK.x+RACK.w && y>RACK.y && y<RACK.y+RACK.d));
        }
        anterior=ponto;
      }
    }
    """)


def test_caminhos_contornam_mesa_mesinha_e_vasos():
    rodar(r"""
    const {rota,FOLGA} = carregar(raiz + 'caminhos.ts');
    const {MESA,MESINHA:m,ASSENTOS} = carregar(raiz + 'cenario.ts');
    const pontos = [{x:1.75,y:3.25}, {x:2.35,y:1.95}, {x:3.75,y:1.95},
      {x:6.75,y:1.7}, {x:10.4,y:1.9}, ...ASSENTOS.map(p=>({x:p.x,y:p.y})),
      {x:1.75,y:5.25}, {x:2.01,y:6.95}, {x:10.05,y:5.6}];
    for (const de of pontos) for (const ate of pontos) {
      const caminho = rota(de, ate, ASSENTOS); assert.ok(caminho.length, JSON.stringify({de,ate}));
      assert.deepEqual(caminho.at(-1), ate);
      let anterior = de;
      for (const p of caminho) {
        for (let i = 0; i <= 100; i++) {
          const x = anterior.x + (p.x-anterior.x)*i/100, y = anterior.y+(p.y-anterior.y)*i/100;
          assert.ok(Math.hypot(x-MESA.x,y-MESA.y) >= MESA.r + FOLGA - 1e-8);
          assert.ok(!(x>m.x && x<m.x+m.w && y>m.y && y<m.y+m.d), 'atravessou a mesinha');
          assert.ok(Math.hypot(x-6.6,y-9.45) > .3, 'atravessou o vaso');
        }
        anterior = p;
      }
    }
    const de = {x:2.01,y:8}, ate = {x:4.8,y:8};
    assert.ok(rota(de,ate).length > 1, JSON.stringify(rota(de,ate)));
    assert.deepEqual(rota(de,{x:m.x+m.w/2,y:m.y+m.d/2}),[]);
    """)


def test_um_canvas_renderiza_corujas_anel_e_piscar_sem_deslocar_os_olhos():
    rodar(r"""
    const renders = []; let capturas = 0, removido = false;
    class Renderer {
      constructor() {
        this.domElement = {setAttribute(){}, remove(){removido=true}, toDataURL(){capturas++; return 'data:image/png;base64,retrato'}};
        this.info = {render:{calls:1,triangles:1}};
      }
      getContext(){return {}} setPixelRatio(){} setSize(){} setClearColor(){}
      render(scene,cam){scene.updateMatrixWorld(true); renders.push({scene,cam})}
      dispose(){} forceContextLoss(){}
    }
    global.window = {devicePixelRatio:1};
    dublês.set(path.resolve(raiz+'recortes3d.ts'), {recorte3D(){return null}});
    const originalRequire = require;
    const tres = {...THREE, WebGLRenderer:Renderer};
    const fonte = fs.readFileSync(raiz+'coruja3d.ts','utf8');
    const codigo = ts.transpileModule(fonte,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
    const modulo = {exports:{}};
    new Function('require','exports',codigo)(nome => nome==='three' ? tres :
      nome.startsWith('.') ? carregar(raiz+nome.slice(2)+'.ts') : originalRequire(nome),modulo.exports);
    const motor = modulo.exports.criar3D(); assert.ok(motor);
    const cores = {penas:'#3f72b3',asas:'#2d588f',barriga:'#b4cff0',olho:'#5ab0ff'};
    const coruja = () => ({cores,acessorios:{},pose:'parado',andando:false,falando:false,fase:0,yaw:0,yawAlvo:0,piscandoAte:0});
    for (let i=0;i<9;i++) {motor.montar('a'+i,coruja()); motor.posicionar('a'+i,2+i,4,.45)}
    motor.destacar('a0',true); motor.desenhar(); assert.equal(renders.length,1); assert.equal(capturas,0);
    const scene = renders[0].scene;
    const modelos = scene.children.filter(g=>g.name==='esc-coruja3d');
    assert.equal(modelos.length,9);
    const m = modelos[0], corpo = m.children[0];
    const penasDaCauda=corpo.children.filter(p=>p.isMesh && p.material.color.equals(new THREE.Color(cores.asas)));
    assert.ok(penasDaCauda.length);
    for(const p of penasDaCauda) {
      p.geometry.computeBoundingBox();
      assert.ok(p.geometry.boundingBox.min.z > -.4, 'cauda saliente demais');
    }
    const olhos = corpo.children.find(g=>g.isGroup && g.position.y===.67);
    assert.ok(olhos); const antes = olhos.getWorldPosition(new THREE.Vector3());
    const o = coruja(); o.piscandoAte = performance.now()+1000;
    motor.posar('a0',o,1/30,true); scene.updateMatrixWorld(true);
    assert.ok(antes.distanceTo(olhos.getWorldPosition(new THREE.Vector3()))<1e-8);
    assert.equal(olhos.scale.y,.12);
    assert.equal(olhos.children.filter(m=>m.isMesh).length,4);
    o.pose='pausado'; motor.posar('a0',o,1/30,true);
    assert.equal(olhos.visible,false);
    const vizinho=modelos[1].children[0];
    assert.ok(vizinho.children.some(m=>m.isMesh && m.material.color.getHexString()==='3f72b3'));
    o.pose='trabalhando'; o.piscandoAte=0; motor.posar('a0',o,1/30,true);
    assert.equal(olhos.visible,true);
    assert.ok(corpo.children.some(m=>m.isMesh && m.material.color.getHexString()==='3f72b3'));
    const anel = scene.children.find(g=>g.isMesh && g.geometry.type==='RingGeometry' && g.visible);
    assert.ok(anel); motor.posicionar('a0',7,8,.1); motor.desenhar();
    assert.deepEqual(m.position.toArray(),[7,.1,8]);
    assert.deepEqual(anel.position.toArray(),[7,.115,8]);
    const pos = m.position.clone(), rot = m.rotation.clone();
    assert.ok(motor.retrato('a0').startsWith('data:image/png')); assert.equal(capturas,1);
    assert.ok(m.position.equals(pos)); assert.ok(m.rotation.equals(rot));
    const obstaculos = scene.children.find(g=>g.name==='esc-obstaculos');
    const {ASSENTOS,PARTES_DA_CADEIRA}=carregar(raiz+'cenario.ts');
    motor.assentos(ASSENTOS);
    const cadeiras=obstaculos.children.find(g=>g.name==='esc-cadeiras');
    assert.equal(cadeiras.children.length,9);
    scene.updateMatrixWorld(true);
    for(let i=0;i<9;i++) {
      const p=ASSENTOS[i], cadeira=cadeiras.children[i];
      assert.deepEqual(cadeira.position.toArray(),[p.x,0,p.y]);
      assert.equal(cadeira.rotation.y,-p.angulo);
      assert.equal(cadeira.children.length,3);
      PARTES_DA_CADEIRA.forEach(([x,y,z,w,d,h],j)=> {
        const centro=new THREE.Vector3(x+w/2,z+h/2,y+d/2).applyMatrix4(cadeira.matrixWorld);
        const obtido=cadeira.children[j].getWorldPosition(new THREE.Vector3());
        assert.ok(centro.distanceTo(obtido)<1e-8);
      });
    }
    const antigas=cadeiras.children.flatMap(g=>g.children); let descartadas=0;
    antigas.forEach(m=>m.geometry.addEventListener('dispose',()=>descartadas++));
    motor.assentos(ASSENTOS.slice(0,4)); assert.equal(descartadas,27);
    assert.equal(cadeiras.children.length,4);
    motor.assentos([]); assert.equal(cadeiras.children.length,0);
    const mascaras=[]; obstaculos.traverse(x=>{if(x.isMesh) mascaras.push(x)});
    assert.ok(mascaras.length>=20);
    assert.ok(mascaras.every(x=>x.material.colorWrite===false && x.material.depthWrite===true && x.renderOrder===-1));
    motor.remover('a0'); assert.equal(scene.children.includes(m),false);
    assert.equal(scene.children.includes(anel),false);
    motor.destruir(); assert.equal(removido,true);
    """)


def test_janela_contem_folhas_e_todos_os_assentos_tem_encosto():
    rodar(r"""
    const {cenarioEstatico,banquinho} = carregar(raiz+'cenario.ts');
    const svg = cenarioEstatico();
    const inicio = svg.indexOf('<g clip-path="url(#esc-vidro)">'), fim = svg.indexOf('</g>',inicio);
    assert.ok(inicio>=0);
    assert.ok(svg.slice(inicio,fim).includes('<ellipse cx="2.5"'));
    for (const direcao of ['o','n','l','s']) {
      const cadeira = banquinho(6,6,direcao);
      assert.equal((cadeira.match(/<polygon/g)||[]).length,9);
    }
    """)


def test_recorte_do_objeto_preserva_silhueta_e_profundidade():
    rodar(r"""
    const formas = new THREE.ShapePath();
    formas.moveTo(20,30); formas.lineTo(60,30); formas.lineTo(60,80); formas.lineTo(20,80); formas.lineTo(20,30);
    formas.userData = {style:{fill:'#fff',stroke:'none',fillOpacity:1,strokeOpacity:1,opacity:1}};
    global.DOMParser = class {parseFromString(){return {querySelectorAll(){return []}}}};
    global.XMLSerializer = class {serializeToString(){return '<svg/>'}};
    class SVGLoader {parse(){return {paths:[formas]}}}
    const codigo = ts.transpileModule(fs.readFileSync(raiz+'recortes3d.ts','utf8'),{
      compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
    const modulo = {exports:{}};
    new Function('require','exports',codigo)(nome => nome.includes('SVGLoader') ? {SVGLoader} :
      nome.startsWith('.') ? carregar(raiz+nome.slice(2)+'.ts') : require(nome),modulo.exports);
    const {cameraDaSala,QUADRO_DA_SALA:q} = carregar(raiz+'projecao3d.ts');
    const cam = cameraDaSala(), mesh = modulo.exports.recorte3D('<rect/>',6,8,0,cam);
    mesh.updateMatrixWorld(true);
    const pos = mesh.geometry.getAttribute('position');
    for(let i=0;i<pos.count;i++) {
      const p = new THREE.Vector3().fromBufferAttribute(pos,i).applyMatrix4(mesh.matrixWorld).project(cam);
      const x=q.x+(p.x+1)*q.largura/2, y=q.y+(1-p.y)*q.altura/2;
      assert.ok(Math.abs(x-20)<.0001 || Math.abs(x-60)<.0001);
      assert.ok(Math.abs(y-30)<.0001 || Math.abs(y-80)<.0001);
    }
    assert.equal(mesh.material.colorWrite,false); assert.equal(mesh.material.depthWrite,true);
    assert.deepEqual(mesh.position.toArray(),[6,0,8]); assert.equal(mesh.renderOrder,-1);
    """)


def test_nove_residentes_sem_cadeiras_duplicadas_com_pausa_retomada_e_remocao():
    rodar(r"""
    const dom = require('../../tests/fixtures/escritorio_dom.cjs')();
    dublês.set(path.resolve(raiz+'coruja3d.ts'), {criar3D:()=>dom.motor});
    const {Escritorio}=carregar(raiz+'escritorio.ts');
    const sala=new Escritorio(dom.host,{aoSelecionar(){}}); dom.silenciarVoltas(sala);
    const cores={penas:'#3f72b3',asas:'#2d588f',barriga:'#b4cff0',olho:'#5ab0ff'};
    const lista=Array.from({length:9},(_,i)=>({nome:'colega'+i,rotulo:'Colega'+i,familia:'geral',pose:'parado',cores,acessorios:{}}));
    async function testar() {
      sala.sincronizar(lista);
      assert.equal(sala.corujas.size,9); assert.equal(new Set([...sala.corujas.values()].map(o=>o.posto)).size,9);
      assert.equal(dom.modelos.size,9); sala.sincronizar(lista); assert.equal(dom.montagens.length,9);
      const noSofa=sala.corujas.get('colega0');
      const ida=sala.andar(noSofa,'sofaB'); await dom.passar(sala,25); await ida;
      assert.equal(noSofa.postoAtual,'sofaB');
      const volta=sala.andar(noSofa,noSofa.posto);
      assert.ok(noSofa.caminho.some(p=>Math.abs(p.x-2.01)<1e-8 && Math.abs(p.y-8.55)<1e-8));
      await dom.passar(sala,25); await volta; assert.equal(noSofa.postoAtual,noSofa.posto);
      assert.equal(sala.cadeiras.size,9); assert.equal(sala.assentos.length,9);
      sala.sentarNaMesa(lista.map(r=>r.nome)); await dom.passar(sala,25);
      const sentados=[...sala.corujas.values()].filter(o=>o.naMesa);
      assert.equal(sentados.length,9); assert.equal(new Set(sentados.map(o=>o.naMesa)).size,9);
      assert.ok(sentados.every(o=>o.naMesa===o.postoAtual && !o.andando));
      assert.ok(sentados.every(o=>!sala.podeSair(o)));
      sala.levantarDaMesa(lista.map(r=>r.nome)); await dom.passar(sala,25);
      assert.ok(sentados.every(o=>o.postoAtual===o.posto && !o.naMesa));
      sala.pedidoChegou('colega0'); await dom.passar(sala,.5);
      const o=sala.corujas.get('colega0'); assert.equal(o.andando,true);
      sala.sincronizar(lista.map(r=>r.nome===o.r.nome ? {...r,pose:'pausado'} : r));
      const pos=[o.x,o.y,o.z]; await dom.passar(sala,3); assert.deepEqual([o.x,o.y,o.z],pos);
      sala.sincronizar(lista.map(r=>r.nome===o.r.nome ? {...r,pose:'trabalhando'} : r));
      let anterior={x:o.x,y:o.y};
      await dom.passar(sala,35,()=>{
        assert.ok(Math.hypot(o.x-anterior.x,o.y-anterior.y)<=.09);
        anterior={x:o.x,y:o.y};
      });
      assert.equal(o.postoAtual,o.posto); assert.equal(o.andando,false); assert.equal(o.real,'trabalhando');
      assert.equal(dom.montagens.length,9);
      sala.sentarNaMesa(lista.map(r=>r.nome)); await dom.passar(sala,1);
      const dono=sentados[0]; const lugar=dono.naMesa;
      sala.sincronizar(lista.filter(r=>r.nome!==dono.r.nome));
      assert.equal(sala.reservados.has(lugar),false); assert.equal(dom.modelos.size,8);
      assert.equal(sala.cadeiras.size,8);
      sala.pedidoChegou('colega1'); await dom.passar(sala,.5);
      const saindo=sala.corujas.get('colega1'); sala.sincronizar(lista.filter(r=>r.nome!==dono.r.nome && r.nome!=='colega1'));
      await dom.passar(sala,1); assert.equal(saindo.ocupado,0); assert.equal(saindo.cancelarCaminho,null);
      sala.destruir(); await Promise.resolve(); assert.equal(dom.modelos.size,0); assert.equal(dom.host.children.length,0);
    }
    testar().catch(e=>{console.error(e);process.exitCode=1});
    """)


def test_sofa_tem_dois_lugares_e_so_libera_entrada_quando_o_corpo_sai():
    rodar(r"""
    Math.random=()=>0;
    const dom=require('../../tests/fixtures/escritorio_dom.cjs')();
    dublês.set(path.resolve(raiz+'coruja3d.ts'),{criar3D:()=>dom.motor});
    const {Escritorio}=carregar(raiz+'escritorio.ts');
    const {FOLGA}=carregar(raiz+'caminhos.ts');
    const sala=new Escritorio(dom.host,{aoSelecionar(){}}); dom.silenciarVoltas(sala);
    const cores={penas:'#3f72b3',asas:'#2d588f',barriga:'#b4cff0',olho:'#5ab0ff'};
    const lista=Array.from({length:9},(_,i)=>({nome:'colega'+i,rotulo:'Colega'+i,familia:'geral',pose:'parado',cores,acessorios:{}}));
    async function testar() {
      sala.sincronizar(lista);
      const corujas=[...sala.corujas.values()];
      const passeios=corujas.map(o=>sala.volta(o,'sofa'));
      assert.equal(passeios.filter(Boolean).length,2);
      assert.deepEqual([...sala.reservados.keys()].sort(),['sofaA','sofaB']);
      assert.equal(corujas[0].fora,'sofaA'); assert.equal(corujas[1].fora,'sofaB');
      sala.agir(corujas[0],passeios[0]); sala.agir(corujas[1],passeios[1]);
      for(let i=0;i<300 && !corujas.slice(0,2).every(o=>o.postoAtual.startsWith('sofa'));i++) await dom.passar(sala,.1);
      assert.equal(corujas[0].postoAtual,'sofaA'); assert.equal(corujas[1].postoAtual,'sofaB');
      assert.ok(Math.hypot(corujas[0].x-corujas[1].x,corujas[0].y-corujas[1].y)>FOLGA*2);
      assert.equal(sala.volta(corujas[2],'sofa'),null);
      const assento={x:corujas[0].x,y:corujas[0].y};
      sala.sincronizar(lista.map((r,i)=>i===0 ? {...r,pose:'pausado'} : r));
      await dom.passar(sala,.5);
      assert.equal(sala.reservados.has('sofaA'),false);
      assert.equal(corujas[0].x,assento.x); assert.equal(corujas[0].y,assento.y);
      assert.equal(sala.volta(corujas[2],'sofa'),null);
      sala.sincronizar(lista.map((r,i)=>i===0 ? {...r,pose:'trabalhando'} : r));
      for(let i=0;i<100 && Math.hypot(corujas[0].x-assento.x,corujas[0].y-assento.y)<FOLGA*2;i++) await dom.passar(sala,.1);
      assert.ok(Math.hypot(corujas[0].x-assento.x,corujas[0].y-assento.y)>=FOLGA*2);
      const novo=sala.volta(corujas[2],'sofa'); assert.equal(typeof novo,'function');
      assert.equal(corujas[2].fora,'sofaA'); sala.agir(corujas[2],novo);
      // Remover e repor no mesmo ciclo mantém a reserva de quem substituiu o ocupante.
      sala.sincronizar(lista.filter((r,i)=>i!==2).map((r,i)=>i===0 ? {...r,pose:'trabalhando'} : r));
      const substituto=sala.volta(corujas[3],'sofa'); assert.equal(typeof substituto,'function');
      assert.equal(sala.reservados.get('sofaA'),corujas[3]);
      sala.agir(corujas[3],substituto);
      await dom.passar(sala,.1);
      assert.equal(sala.reservados.get('sofaA'),corujas[3]);
      sala.destruir(); assert.equal(sala.reservados.size,0); await dom.passar(sala,.1);
      assert.equal(sala.reservados.size,0);
    }
    testar().catch(e=>{console.error(e);process.exitCode=1});
    """)


def test_cadeiras_acompanham_lotacao_sem_mover_assentos_ou_recriar_corujas():
    rodar(r"""
    const dom=require('../../tests/fixtures/escritorio_dom.cjs')();
    const alteracoes=[]; dom.motor.assentos=ps=>alteracoes.push(ps.map(p=>({...p})));
    dublês.set(path.resolve(raiz+'coruja3d.ts'),{criar3D:()=>dom.motor});
    const {Escritorio}=carregar(raiz+'escritorio.ts');
    const {ASSENTOS,MESA}=carregar(raiz+'cenario.ts');
    const sala=new Escritorio(dom.host,{aoSelecionar(){}}); dom.silenciarVoltas(sala);
    const cores={penas:'#3f72b3',asas:'#2d588f',barriga:'#b4cff0',olho:'#5ab0ff'};
    const lista=Array.from({length:10},(_,i)=>({nome:'colega'+i,rotulo:'Colega'+i,familia:'geral',pose:'parado',cores,acessorios:{}}));
    async function testar() {
      for(let n=1;n<=9;n++) {
        const anteriores=new Map(sala.cadeiras);
        sala.sincronizar(lista.slice(0,n));
        assert.equal(sala.cadeiras.size,n); assert.equal(sala.assentos.length,n);
        assert.equal(dom.montagens.length,n);
        for(const p of sala.assentos) {
          const original=ASSENTOS.find(a=>a.nome===p.nome);
          assert.deepEqual(p,original);
          if(anteriores.has(p.nome)) assert.equal(sala.cadeiras.get(p.nome),anteriores.get(p.nome));
          for(const outra of sala.assentos) if(p!==outra) assert.ok(Math.hypot(p.x-outra.x,p.y-outra.y)>1.4);
          assert.ok(Math.hypot(p.x-MESA.x,p.y-MESA.y)>MESA.r+.68);
          assert.ok(Math.abs(Math.sin(p.angulo)-(p.x-MESA.x)/2.1)<1e-8);
          assert.ok(Math.abs(-Math.cos(p.angulo)-(p.y-MESA.y)/2.1)<1e-8);
        }
        const antes=alteracoes.length;
        sala.sincronizar(lista.slice(0,n).map(r=>({...r,pose:'trabalhando'})));
        assert.equal(alteracoes.length,antes);
        assert.equal(dom.montagens.length,n);
        sala.sentarNaMesa(lista.slice(0,n).map(r=>r.nome)); await dom.passar(sala,30);
        const sentados=[...sala.corujas.values()];
        assert.equal(new Set(sentados.map(o=>o.naMesa)).size,n);
        assert.ok(sentados.every(o=>o.naMesa && o.postoAtual===o.naMesa && !o.andando));
        sala.sentarNaMesa(lista.slice(0,n).map(r=>r.nome));
        assert.equal(sala.reservados.size,n);
        sala.levantarDaMesa(lista.slice(0,n).map(r=>r.nome)); await dom.passar(sala,30);
        assert.ok(sentados.every(o=>!o.naMesa && o.postoAtual===o.posto));
      }
      sala.sincronizar(lista); assert.equal(sala.corujas.size,9); assert.equal(sala.cadeiras.size,9);
      sala.sentarNaMesa(lista.map(r=>r.nome)); await dom.passar(sala,30);
      for(const n of [8,6,4,2,0]) {
        sala.sincronizar(lista.slice(0,n));
        assert.equal(sala.cadeiras.size,n); assert.equal(sala.assentos.length,n);
        assert.equal(sala.reservados.size,n);
        assert.ok([...sala.corujas.values()].every(o=>sala.cadeiras.has(o.naMesa)));
      }
      assert.equal(sala.objetos.filter(o=>o.el.getAttribute('data-assento')).length,0);
      sala.destruir();
    }
    testar().catch(e=>{console.error(e);process.exitCode=1});
    """)


def test_malhas_juntas_preservam_posicoes_materiais_e_partes_moveis():
    rodar(r"""
    const {juntarMalhas}=carregar(raiz+'malhas3d.ts');
    const g=new THREE.Group(), movel=new THREE.Group(); g.add(movel);
    const primeira=new THREE.Mesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshStandardMaterial({color:'#668b68'}));
    const segunda=new THREE.Mesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshStandardMaterial({color:'#668b68'}));
    primeira.position.set(2,0,0); segunda.position.set(4,0,0);
    g.add(primeira,segunda);
    movel.add(new THREE.Mesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshStandardMaterial({color:'#668b68'})));
    juntarMalhas(g,new Set([movel]));
    assert.equal(g.children.length,2); assert.equal(movel.children.length,1);
    const unida=g.children.find(o=>o.isMesh); unida.geometry.computeBoundingBox();
    assert.equal(unida.geometry.boundingBox.min.x,1.5); assert.equal(unida.geometry.boundingBox.max.x,4.5);
    assert.equal(unida.material.color.getHexString(),'668b68');
    assert.equal(unida.geometry.getAttribute('position').count,72);
    """)


def test_fechar_um_assunto_nao_tira_quem_ainda_participa_de_outro():
    rodar(r"""
    const {EventosDaSala}=carregar(raiz+'eventosDaSala.ts');
    const trilha=new EventosDaSala(), levantaram=[], falas=[];
    const sala={ativa:()=>true,reconciliarMesa(){},sentarNaMesa(){},levantarDaMesa:ns=>levantaram.push(...ns),falar:(n,t)=>falas.push(t),pedidoChegou(){}};
    const base={em:1,tipo:'mesa_aberta',agente:'pessoa',tarefa:'a',assunto:'a',participantes:['lina','caio'],
      origem:'mesa:a',pedido:'Revisão',texto:'',para:''};
    const segundo={...base,em:2,tarefa:'b',assunto:'b',participantes:['caio','vera']};
    const ler=e=>({fala:e.texto,para:e.para});
    trilha.receber([base,segundo],true,sala,ler);
    trilha.receber([{...base,em:3,tipo:'mesa_fechada'}],true,sala,ler);
    assert.deepEqual(levantaram,['lina']);
    trilha.receber([{...segundo,em:4,tipo:'mesa_fala',agente:'caio',texto:'Conferido'}],true,sala,ler);
    assert.deepEqual(falas,['Conferido']);
    assert.equal(trilha.receber([{...segundo,em:4,tipo:'mesa_fala',agente:'caio',texto:'Conferido'}],true,sala,ler).length,0);
    """)


def test_eventos_da_hq_real_chegam_ao_motor_sem_repetir_acao(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sentury.residentes import mesa, registro, tarefas, worker
    from sentury.residentes.api_local import router

    monkeypatch.setenv('SENTURY_HOME', str(tmp_path))
    monkeypatch.setenv('SENTURY_HQ_URL', '')
    worker.configurar(None)
    mesa.configurar(None)
    for nome in ('lina', 'caio', 'vera', 'rui', 'bia', 'leo', 'eva', 'tom', 'ana'):
        registro.criar({'nome': nome, 'papel': 'conferência', 'objetivo': 'conferir os dados',
                        'ferramentas': ['ler_arquivo']})
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        tarefa = tarefas.enfileirar('lina', 'Conferir os dados', 'tela')
        tarefas.comecar(tarefa.id)
        tarefas.esperar(tarefa.id, 'aprovação', pendente='ler_arquivo')
        esperando = client.get('/sentury/residentes/_esperando').json()
        registro.mudar_estado('caio', 'trabalhando')
        registro.pausar('vera')
        agentes = client.get('/sentury/residentes').json()
        aberto = client.post('/sentury/residentes/_mesa', json={'titulo': 'Revisão', 'texto': '@rui @bia'}).json()
        mesa.falar(aberto['id'], 'rui', '@bia confira os dados')
        eventos_abertos = client.get('/sentury/residentes/_eventos').json()
        client.post(f"/sentury/residentes/_mesa/{aberto['id']}/fechar", json={'resumo': 'Dados conferidos'})
        tarefas.concluir(tarefa.id, 'Conferido')
        eventos_fechados = client.get('/sentury/residentes/_eventos').json()
    dados = {'agentes': agentes, 'esperando': esperando, 'abertos': eventos_abertos, 'fechados': eventos_fechados}
    rodar('const dados=' + json.dumps(dados, ensure_ascii=True) + ';' + r"""
    const dom=require('../../tests/fixtures/escritorio_dom.cjs')();
    dublês.set(path.resolve(raiz+'coruja3d.ts'),{criar3D:()=>dom.motor});
    dublês.set(path.resolve('src/runtime/config.ts'),{authHeaders:()=>({})});
    dublês.set(path.resolve('src/transport/http-client.ts'),{apiClient:{get:async p=>
      p.includes('_esperando') ? dados.esperando : p.includes('_eventos') ? dados.abertos : dados.agentes}});
    const {residentes,estadoDaCoruja}=carregar('src/features/residentes/api.ts');
    const {EventosDaSala}=carregar(raiz+'eventosDaSala.ts');
    const {Escritorio}=carregar(raiz+'escritorio.ts');
    async function testar() {
      const {agentes}=await residentes.listar(), esperando=await residentes.esperando();
      const eventos=await residentes.eventos();
      assert.equal(agentes.length,9); assert.equal(estadoDaCoruja(agentes.find(a=>a.nome==='lina'),esperando),'esperando');
      assert.equal(estadoDaCoruja(agentes.find(a=>a.nome==='caio'),esperando),'trabalhando');
      assert.equal(estadoDaCoruja(agentes.find(a=>a.nome==='vera'),esperando),'pausado');
      const sala=new Escritorio(dom.host,{aoSelecionar(){}}); dom.silenciarVoltas(sala);
      sala.sincronizar(agentes.map(a=>({nome:a.nome,rotulo:a.nome,familia:a.aparencia.familia,
        cores:a.cores,acessorios:a.aparencia.acessorios,pose:estadoDaCoruja(a,esperando)})));
      const trilha=new EventosDaSala(); let chamadas=0;
      const pedido=sala.pedidoChegou.bind(sala); sala.pedidoChegou=n=>{chamadas++;pedido(n)};
      const ler=e=>({fala:e.texto || '',para:e.para});
      assert.equal(trilha.receber(eventos,true,sala,ler).length,eventos.length);
      assert.equal(trilha.receber(eventos,true,sala,ler).length,0); assert.equal(chamadas,1);
      const novas=trilha.receber(dados.fechados.eventos,true,sala,ler);
      assert.ok(novas.some(e=>e.tipo==='mesa_fechada')); assert.equal(novas.filter(e=>e.tipo==='feita').length,1);
      assert.equal(trilha.receber(dados.fechados.eventos,true,sala,ler).length,0);
      await dom.passar(sala,40);
      assert.equal(sala.reservados.size,0); assert.equal(sala.corujas.get('lina').postoAtual,sala.corujas.get('lina').posto);
      const historico=new EventosDaSala();
      let restaurados=[]; const sentar=sala.sentarNaMesa.bind(sala);
      sala.sentarNaMesa=nomes=>{restaurados=nomes;sentar(nomes)};
      historico.receber(eventos,false,sala,ler);
      assert.deepEqual(new Set(restaurados),new Set(['rui','bia']));
      assert.equal(historico.mesas.size,1);
      sala.destruir();
    }
    testar().catch(e=>{console.error(e);process.exitCode=1});
    """)


def test_fala_longa_quebra_em_linhas_no_balao():
    """Um balão de uma linha cortava a fala em 52 caracteres, no meio da frase;
    agora ela quebra em até três linhas e só o excesso vira reticências."""
    rodar(r"""
    const {linhasDoBalao}=carregar(raiz+'escritorio.ts');
    assert.deepEqual(linhasDoBalao('Pronto: relatório salvo'), ['Pronto: relatório salvo']);
    const longa='Meu principal risco é fornecedor falhar, reajustar ou cobrar extras na última hora.';
    const l=linhasDoBalao(longa);
    assert.equal(l.length,2);
    assert.equal(l.join(' '),longa);
    assert.ok(l.every(x=>x.length<=46));
    const e=linhasDoBalao(longa.repeat(4));
    assert.equal(e.length,3);
    assert.ok(e[2].endsWith('…') && e.every(x=>x.length<=47));
    """)
