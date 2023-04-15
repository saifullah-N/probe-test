import { get, writable } from "svelte/store";
// import { processNetworkInfo } from "./NetworkInfo";
import {PUT} from "$lib/api"
export const networkInfo = writable({});

export const probingActive = writable(false);
export const probeContacted = writable(false);
export const probingStarted = writable(false);
export const probingFailed = writable(false);
export const probingComplete = writable(false);

export function handleControllerStateUpdate(state: Record<string, any>) {
    if (get(probingActive)) {
        if (state.pw === 0) {
            PUT("write-log",{handleControllerStateUpdate:[state.pw ,state.log?.msg , state.cycle]});
            probeContacted.set(true);
            PUT("write-log",{probeContacted:true});
            
        }
        
        if (state.log?.msg === "Switch not found") {
            PUT("write-log",{handleControllerStateUpdate:[state.pw ,state.log?.msg , state.cycle]});
            probingFailed.set(true);
        }
        
        if (state.cycle !== "idle") {
            PUT("write-log",{probingFailed:true , cycle:"idle"});
            PUT("write-log",{handleControllerStateUpdate:[state.pw ,state.log?.msg , state.cycle]});
            probingStarted.set(true);
        }
        
        if (state.cycle === "idle" && get(probingStarted)) {
            probingStarted.set(false);
            probingComplete.set(true);
            PUT("write-log",{handleControllerStateUpdate:[state.pw ,state.log?.msg , state.cycle]});
            PUT("write-log",{probingStarted:false , probingComplete:true , cycle:"idle"});
        }
    }
}