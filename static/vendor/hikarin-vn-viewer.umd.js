(function(h,d){typeof exports=="object"&&typeof module<"u"?module.exports=d():typeof define=="function"&&define.amd?define(d):(h=typeof globalThis<"u"?globalThis:h||self,h.HikarinVN=d())})(this,(function(){"use strict";class h{constructor(){this.script=[],this.currentIndex=0,this.STATES={IDLE:"IDLE",PLAYING:"PLAYING",WAITING:"WAITING",CHOICE:"CHOICE",ENDED:"ENDED"},this.state=this.STATES.IDLE,this.variables={},this.globals={},this.environment={isNight:!1,isDay:!0},this.events={onSay:null,onChoice:null,onShowSprite:null,onRemoveSprite:null,onBackground:null,onAutoSave:null,onSceneNext:null,onFinish:null,onUpdateDebug:null,onLog:null}}_log(e,t,...i){const s={STEP:"color: #00ffff; font-weight: bold;",FLOW:"color: #adff2f;",VAR:"color: #ffa500;",COND:"color: #da70d6;",ERR:"color: #ff4444; font-weight: bold; background: #220000"};if(console&&console.log&&console.log(`%c[${e}] ${t}`,s[e]||"",...i),this.events.onLog){const n={category:e,message:t,args:i,timestamp:new Date};this.events.onLog(n)}}loadScript(e,t={},i={}){this.script=JSON.parse(JSON.stringify(e)),this.globals={...t},this.variables={...i},this.currentIndex=0,this.state=this.STATES.IDLE,this._log("FLOW","Script Loaded. Total Steps: "+this.script.length),this._updateDebug()}start(e=null){if(this.script.length!==0){if(this.state=this.STATES.PLAYING,!e&&this.variables._autosave){const t=this.variables._autosave;this._log("FLOW",`Found '_autosave' variable. Resuming at label: '${t}'`),e=t}e?(this._log("FLOW",`Starting execution at label: ${e}`),this._jump(e)):(this.currentIndex=0,this._step()),this._updateDebug()}}stop(){this.state=this.STATES.IDLE,this._updateDebug()}advance(){this.state===this.STATES.WAITING&&(this.state=this.STATES.PLAYING,this.currentIndex++,this._step())}selectChoice(e){this.state===this.STATES.CHOICE&&(this._log("FLOW",`Player selected choice -> Jumping to '${e}'`),this._jump(e))}setEnvironment(e,t){this.environment.hasOwnProperty(e)?(this._log("FLOW",`Environment updated: ${e} set to ${t}`),this.environment[e]=t,this._updateDebug()):this._log("WARN",`Attempted to set unknown environment key: '${e}'`)}setVariable(e,t){this._log("VAR",`External set LOCAL variable: '${e}' =`,t),this.variables[e]=t,this._updateDebug()}setGlobal(e,t){this._log("VAR",`External set GLOBAL variable: '${e}' =`,t),this.globals[e]=t,this._updateDebug()}getVariable(e){return this.variables[e]}getGlobal(e){return this.globals[e]}deleteVariable(e){this.variables.hasOwnProperty(e)&&(this._log("VAR",`External delete LOCAL variable: '${e}'`),delete this.variables[e],this._updateDebug())}deleteGlobal(e){this.globals.hasOwnProperty(e)&&(this._log("VAR",`External delete GLOBAL variable: '${e}'`),delete this.globals[e],this._updateDebug())}_step(){if(this.currentIndex>=this.script.length){this._finish();return}const e=this.script[this.currentIndex],t=()=>{this.currentIndex++,setTimeout(()=>this._step(),0)};switch(this._log("STEP",`[ID:${e.id}] TYPE: ${e.type}`),e.type){case"conditional":case"conditional_global":this._checkCondition(e)?(this._log("COND","Condition PASSED. Continuing flow."),t()):e.end!==void 0?(this._log("COND",`Condition FAILED. Skipping to ID: ${e.end}`),this._jumpToId(e.end)):(this._log("ERR","Condition Failed but no 'end' ID provided!"),t());break;case"label":case"start":case"meta":case"command":e.type==="meta"&&(e.action==="create_var"&&(this.variables[e.var]=e.init),e.action==="create_global"&&this.globals[e.var]===void 0&&(this.globals[e.var]=e.init),this._updateDebug()),t();break;case"transition":this._jump(e.label);break;case"next":this.variables._autosave=e.label,this.events.onAutoSave&&this.events.onAutoSave(e.label),this._updateDebug(),t();break;case"dialogue":this.state=this.STATES.WAITING,this.events.onSay&&this.events.onSay(this._parseString(e.label),this._parseString(e.content)),this._updateDebug();break;case"choice":this.state=this.STATES.CHOICE,this.events.onChoice&&this.events.onChoice(e.choice),this._updateDebug();break;case"show_sprite":let s=null;if(e.dyn_location){const a=this._parseString(e.dyn_location);/<.*?>/.test(a)?this._log("WARN",`Dynamic sprite '${e.dyn_location}' failed to resolve vars. Falling back.`):s=a}s||(s=this._parseString(e.location)),this.events.onShowSprite&&this.events.onShowSprite({...e,finalLocation:s}),t();break;case"remove_sprite":this.events.onRemoveSprite&&this.events.onRemoveSprite(e.sprite),t();break;case"modify_background":this.events.onBackground&&this.events.onBackground(e.background),t();break;case"unlock_dialogues":const n=e.events||[];Array.isArray(this.variables._unlocked_dialogues)||(this.variables._unlocked_dialogues=[]);const l=[];n.forEach(a=>{this.variables._unlocked_dialogues.includes(a)||(this.variables._unlocked_dialogues.push(a),l.push(a))}),l.length>0&&(this._log("VAR",`Unlocked dialogues: ${l.join(", ")}`),this._updateDebug()),t();break;case"idle_chat":const r=this.variables._unlocked_dialogues;if(Array.isArray(r)&&r.length>0){const a=Math.floor(Math.random()*r.length),c=r[a];this._log("FLOW",`Performing idle chat. Randomly selected: '${c}'`),this._jump(c)}else this._log("WARN","Idle chat triggered, but '_unlocked_dialogues' is empty or not found. Skipping."),t();break;case"random_dialogue":const o=e.events;if(Array.isArray(o)&&o.length>0){const a=Math.floor(Math.random()*o.length),c=o[a];this._log("FLOW",`Performing random dialogue. Randomly selected: '${c}'`),this._jump(c)}else this._log("WARN","Random dialogue triggered, but 'events' array is empty or not found. Skipping."),t();break;case"modify_variable":this._modVar(this.variables,e,"Local"),t();break;case"modify_global":this._modVar(this.globals,e,"Global"),t();break;case"finish_dialogue":this._finish();break;default:this._log("ERR",`Unknown Instruction: ${e.type}`),t();break}}_jumpToId(e){let t=-1;for(let i=0;i<this.script.length;i++)if(this.script[i].id===e){t=i;break}t!==-1?(this.currentIndex=t,this.state=this.STATES.PLAYING,setTimeout(()=>this._step(),0)):this._log("ERR",`CRITICAL: Could not find step with ID: ${e}`)}_processMeta(e){e.action==="create_var"?this.variables[e.var]=e.init:e.action==="create_global"&&this.globals[e.var]===void 0&&(this.globals[e.var]=e.init),this._updateDebug()}_jump(e){let t=-1;for(let i=0;i<this.script.length;i++)if(this.script[i].type==="label"&&this.script[i].label===e){t=i;break}t!==-1?(this._log("FLOW",`Jump Successful. Moving Index ${this.currentIndex} -> ${t}`),this.currentIndex=t,this.state=this.STATES.PLAYING,setTimeout(()=>this._step(),0)):this._log("ERR",`CRITICAL: Label '${e}' not found!`)}_modVar(e,t){const i=t.var;e[i]===void 0&&(e[i]=0),t.action==="modify_var"?e[i]=t.value:t.action==="increment_var"?e[i]+=t.value:t.action==="subtract_var"&&(e[i]-=t.value),this._updateDebug()}_checkCondition(e){const t=e.var,i=e.value;let s;this.environment.hasOwnProperty(t)?(this._log("COND",`Checking Environment property: '${t}'`),s=this.environment[t]):e.type==="conditional_global"?(this._log("COND",`Checking Global variable: '${t}'`),s=this.globals[t]!==void 0?this.globals[t]:0):(this._log("COND",`Checking Local variable: '${t}'`),s=this.variables[t]!==void 0?this.variables[t]:0);let n=!1;return e.condition==="equal"&&(n=s===i),e.condition==="not_equal"&&(n=s!==i),e.condition==="greater_than"&&(n=s>i),e.condition==="less_than"&&(n=s<i),this._log("COND",`Check '${t}' (${s}) ${e.condition} '${i}'? Result: ${n}`),n}_parseString(e){return e?e.replace(/<(.+?)>/g,(t,i)=>this.globals[i]!==void 0?this.globals[i]:this.variables[i]!==void 0?this.variables[i]:`<${i}>`):""}_finish(){this.state=this.STATES.ENDED,this.events.onFinish&&this.events.onFinish(),this._updateDebug()}_updateDebug(){this.events.onUpdateDebug&&this.events.onUpdateDebug(this.globals,this.variables,this.state)}}class d{constructor(e,t,i={}){if(this.container=document.getElementById(e),!this.container)throw new Error(`HikarinVN: Container #${e} not found.`);this.runtime=t,this.assetsPath=i.assetsPath||"",this.debugMode=i.debug||!1,this.styles=`
            /* RESET */
            .hvn-wrapper * { box-sizing: border-box; user-select: none; -webkit-user-select: none; }
            
            /* WRAPPER */
            .hvn-wrapper {
                width: 100%; height: 100%; display: flex; flex-direction: column;
                background: #111; font-family: 'Segoe UI', Consolas, sans-serif;
            }

            /* STAGE */
            .hvn-stage {
                position: relative; width: 100%; aspect-ratio: 16 / 9; 
                background: #000; overflow: hidden; color: white; flex-shrink: 0; 
            }

            .hvn-layer { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; }
            
            /* UI Layer */
            .hvn-ui-layer { 
                z-index: 50; pointer-events: auto; display: flex; flex-direction: column; 
                justify-content: flex-end; padding: 20px;
            }

            /* Sprites */
            .hvn-sprite {
                position: absolute; background-size: contain; background-repeat: no-repeat;
                background-position: center bottom; transition: opacity 0.2s; z-index: 10;
            }
            
            /* ERROR STATE FOR MISSING IMAGES */
            .hvn-missing-asset {
                border: 2px solid red !important;
                background-color: rgba(255, 0, 0, 0.2);
            }
            .hvn-missing-asset::after {
                content: 'MISSING'; position: absolute; top: 50%; left: 50%;
                transform: translate(-50%, -50%); color: red; font-weight: bold; background: black;
            }

            /* Dialogue Box */
            .hvn-dialogue-box {
                background: rgba(0, 0, 0, 0.85); border: 2px solid #555; border-radius: 4px;
                padding: 20px; min-height: 140px; display: none; margin-bottom: 0px; 
                pointer-events: auto; box-shadow: 0 4px 10px rgba(0,0,0,0.5);
            }
            .hvn-dialogue-box.active { display: block !important; }
            
            .hvn-char-name { color: #ff9999; font-weight: bold; font-size: 1.4em; margin-bottom: 10px; }
            .hvn-char-text { font-size: 1.2em; line-height: 1.5; color: #eee; }

            /* Choices */
            .hvn-choice-layer {
                z-index: 100; pointer-events: auto; display: flex; flex-direction: column; 
                align-items: center; justify-content: center; gap: 15px; background: rgba(0,0,0,0.8); 
                display: none;
            }
            .hvn-choice-layer.active { display: flex !important; }
            
            .hvn-choice-btn {
                background: #eee; color: #222; border: 2px solid #aaa; padding: 12px 50px;
                font-size: 18px; cursor: pointer; min-width: 300px; text-align: center;
                transition: 0.2s; border-radius: 4px; font-weight: bold;
            }
            .hvn-choice-btn:hover { background: #ffcc00; border-color: #fff; transform: scale(1.05); }

            /* DEBUG PANEL */
            .hvn-debug-panel {
                width: 100%; height: 150px; background: #222; border-top: 1px solid #444;
                display: flex; font-size: 12px; color: #fff; overflow: hidden; flex-shrink: 0; 
            }
            
            .hvn-debug-col { flex: 1; padding: 10px; overflow-y: auto; border-right: 1px solid #333; }
            .hvn-d-title { display:block; border-bottom:1px solid #555; margin-bottom:5px; color:#aaa; font-weight:bold;}
            .hvn-var-row { display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding: 2px 0; }
        `,this._injectStyles(),this._buildDOM(),this._bindEvents()}_verifyImageLoad(e,t,i){const s=new Image;s.src=e,s.onerror=()=>{const n=`[HikarinVN Error] Failed to load image: "${e}"`,l=`Context: ${t}`;console.group(n),console.error(l),console.warn("Check if the file exists in your assets folder and the path is correct."),console.groupEnd(),this.debugMode&&i&&(i.classList.add("hvn-missing-asset"),i.title=`MISSING: ${e}`)},s.onload=()=>{i&&i.classList.remove("hvn-missing-asset")}}_injectStyles(){if(!document.getElementById("hvn-embedded-styles")){const e=document.createElement("style");e.id="hvn-embedded-styles",e.innerHTML=this.styles,document.head.appendChild(e)}}_buildDOM(){this.container.innerHTML=`
            <div class="hvn-wrapper">
                <div class="hvn-stage">
                    <div class="hvn-layer hvn-bg-layer" style="z-index: 1;"></div>
                    <div class="hvn-layer hvn-sprite-layer" style="z-index: 10;"></div>
                    
                    <div class="hvn-layer hvn-ui-layer">
                        <div class="hvn-dialogue-box">
                            <div class="hvn-char-name"></div>
                            <div class="hvn-char-text"></div>
                        </div>
                    </div>

                    <div class="hvn-layer hvn-choice-layer"></div>
                </div>
                
                ${this.debugMode?`
                <div class="hvn-debug-panel">
                    <div class="hvn-debug-col"><span class="hvn-d-title">GLOBALS</span><div class="d-glob"></div></div>
                    <div class="hvn-debug-col"><span class="hvn-d-title">LOCALS</span><div class="d-loc"></div></div>
                    <div class="hvn-debug-col"><span class="hvn-d-title">STATUS</span><div class="d-stat">IDLE</div></div>
                </div>`:""}
            </div>
        `,this.elBg=this.container.querySelector(".hvn-bg-layer"),this.elSprites=this.container.querySelector(".hvn-sprite-layer"),this.elDBox=this.container.querySelector(".hvn-dialogue-box"),this.elDName=this.container.querySelector(".hvn-char-name"),this.elDText=this.container.querySelector(".hvn-char-text"),this.elChoices=this.container.querySelector(".hvn-choice-layer"),this.debugMode&&(this.elDGlobal=this.container.querySelector(".d-glob"),this.elDLocal=this.container.querySelector(".d-loc"),this.elDStatus=this.container.querySelector(".d-stat"))}_bindEvents(){this.container.querySelector(".hvn-stage").addEventListener("click",e=>{e.target.closest(".hvn-choice-layer")||this.runtime.state===this.runtime.STATES.WAITING&&this.runtime.advance()}),this.runtime.events.onSay=(e,t)=>{this.elChoices.classList.remove("active"),this.elDBox.classList.add("active"),this.elDName.innerText=e||"???",this.elDText.innerText=t||""},this.runtime.events.onChoice=e=>{this.elDBox.classList.remove("active"),this.elChoices.innerHTML="",this.elChoices.classList.add("active"),e.forEach(t=>{const i=document.createElement("div");i.className="hvn-choice-btn",i.innerText=t.display,i.onclick=s=>{s.stopPropagation(),this.elChoices.classList.remove("active"),this.runtime.selectChoice(t.label)},this.elChoices.appendChild(i)})},this.runtime.events.onShowSprite=e=>{const t=`sprite-${e.sprite}`;let i=this.container.querySelector(`#${t}`);i&&i.remove(),i=document.createElement("div"),i.id=t,i.className="hvn-sprite";const s=(e.column-1)/e.wRatio*100,n=(e.row-1)/e.hRatio*100,l=e.wFrameRatio/e.wRatio*100,r=e.hFrameRatio/e.hRatio*100;i.style.left=`${s}%`,i.style.top=`${n}%`,i.style.width=`${l}%`,i.style.height=`${r}%`;const o=this.assetsPath+e.finalLocation;this._verifyImageLoad(o,`Sprite [${e.sprite}]`,i),i.style.backgroundImage=`url('${o}')`,this.debugMode&&(i.classList.contains("hvn-missing-asset")||(i.style.border="1px dashed #0ff"),i.innerText=`${e.sprite}`,i.style.display="flex",i.style.alignItems="center",i.style.justifyContent="center",i.style.textShadow="0 0 4px #000",i.title=e.finalLocation),this.elSprites.appendChild(i)},this.runtime.events.onRemoveSprite=e=>{const t=this.container.querySelector(`[id="sprite-${e}"]`);t?t.remove():console.warn(`Attempted to remove sprite but could not find element with ID: sprite-${e}`)},this.runtime.events.onBackground=e=>{const t=this.assetsPath+e;this._verifyImageLoad(t,"Background Layer",this.elBg),this.elBg.style.background=`url('${t}') center/cover no-repeat`},this.runtime.events.onFinish=()=>{this.elDBox.classList.add("active"),this.elDName.innerText="SYSTEM",this.elDText.innerText="End of Script."},this.debugMode&&(this.runtime.events.onUpdateDebug=(e,t,i)=>{this.elDStatus.innerText=i;const s=(n,l)=>{l.innerHTML=Object.entries(n).map(([r,o])=>`<div class="hvn-var-row"><span style="color:#66d9ef">${r}</span><span style="color:${typeof o=="boolean"?o?"#0f0":"#f00":"#a6e22e"}">${o}</span></div>`).join("")};s(e,this.elDGlobal),s(t,this.elDLocal)})}}class g{constructor(e,t,i={}){this.runtime=new h,this.renderer=new d(e,this.runtime,i);const s=i.globals||{},n=i.variables||{};this.runtime.loadScript(t,s,n)}start(){this.runtime.start()}setEnvironment(e,t){this.runtime.setEnvironment(e,t)}setVariable(e,t){this.runtime.setVariable(e,t)}setGlobal(e,t){this.runtime.setGlobal(e,t)}getVariable(e){return this.runtime.getVariable(e)}getGlobal(e){return this.runtime.getGlobal(e)}deleteVariable(e){this.runtime.deleteVariable(e)}deleteGlobal(e){this.runtime.deleteGlobal(e)}onLog(e){typeof e=="function"&&(this.runtime.events.onLog=e)}}return g}));
