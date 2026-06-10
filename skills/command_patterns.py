"""
skills/command_patterns.py — Command trigger patterns for ARIA
============================================================
Groups and organizes all string matching rules and trigger patterns.
"""

STOP_WORDS = [
    "stop", "cancel", "nevermind", "be quiet", "shut up", "stop talking", 
    "aria stop", "stop aria", "quiet", "silence", "pause", "enough", 
    "ok stop", "that's enough"
]

ADMIN_UNLOCK_WORDS = ["aria unlock", "unlock aria", "activate admin", "unlock admin"]
ADMIN_LOCK_WORDS = ["lock aria", "lock admin", "deactivate admin"]

WEATHER_WORDS = ["weather"]
GITHUB_WORDS = ["github "]

REMINDER_ADD_WORDS = ["remind me to "]
REMINDER_GET_WORDS = ["what are my reminders", "show my reminders", "get my reminders", "list reminders", "my reminders"]
REMINDER_CLEAR_WORDS = ["clear reminders", "delete reminders", "remove reminders"]

FOLDER_REMEMBER_WORDS = ["remember this folder as ", "remember folder as "]

PERSONAL_BRAIN_WORDS = ["what do you know about me", "show my brain", "my brain summary", "personal brain", "what is in my brain"]
GUIDE_ME_WORDS = ["what should i do", "what do i need to do", "what should i focus on", "guide me"]
LAST_SESSION_WORDS = ["last session", "what did we do last", "what did we work on last time", "summary of last session", "previous session"]

WORKSPACE_PREPARE_WORDS = ["prepare ml workspace", "setup coding", "start coding", "ml workspace"]
WORKSPACE_STUDY_WORDS = ["study mode", "activate study mode", "start study", "focus mode"]
WORKSPACE_CLOSE_WORDS = ["close workspace", "clean workspace", "close coding"]

AUTONOMOUS_TASK_RUN_WORDS = ["run task ", "automate ", "aria run "]
AUTONOMOUS_TASK_CANCEL_WORDS = ["cancel task", "abort task", "stop task", "stop execution"]
AUTONOMOUS_TASK_REPLAY_WORDS = ["replay task "]

OLLAMA_LAUNCH_WORDS = ["ollama launch", "launch claude", "launch codex", "launch hermes", "launch openclaw", "launch opencode"]

EXIT_APP_WORDS = ["exit application", "close aria", "quit aria", "shutdown application"]
GOODBYE_WORDS = ["goodbye", "bye", "bye aria", "go to sleep", "see you", "see ya", "talk later"]

RESET_MEMORY_WORDS = ["reset memory", "forget everything", "clear history", "new conversation"]

UI_SWITCH_TO_WORDS = ["switch to", "focus on", "bring up", "go to app"]

BROWSER_TAB_NEW_WORDS = ["new tab"]
BROWSER_NEWS_WORDS = ["latest news", "news of the world", "world news", "what's going on around the world", "what is going on around the world"]
BROWSER_TAB_CLOSE_WORDS = ["close tab", "close the tab", "bar tab", "delete tab", "remove tab"]
BROWSER_WINDOW_CLOSE_WORDS = ["close window", "close the window", "close chrome", "close browser", "close cross", "cross button", "press cross"]
BROWSER_REFRESH_WORDS = ["refresh page", "reload page", "refresh browser"]
BROWSER_BACK_WORDS = ["go back"]
BROWSER_FORWARD_WORDS = ["go forward"]
BROWSER_GO_TO_WORDS = ["go to"]
BROWSER_OPEN_APPS_WORDS = ["what apps are open", "what is open", "list open apps", "show open apps"]

SCREENSHOT_TAKE_WORDS = ["take screenshot", "screenshot", "capture screen"]

SCREEN_READ_TRIGGERS = [
    "read my screen", "read the screen", "what's on my screen",
    "what is on my screen", "what do you see on screen",
    "read it out", "read this page", "read the page",
    "read the results", "read the news", "pick some latest news",
    "summarize the screen", "summarise the screen"
]

SCREEN_TRIAGE_TRIGGERS = [
    "what error is on my screen", "what error on screen", "what's wrong with my code",
    "explain this error", "explain the error", "fix the bug on my screen", "fix this bug",
    "fix error on my screen", "why is my code crashing", "what is crashing", "debug my screen"
]

COGNITIVE_PLANNING_TRIGGERS = [
    "help me study for", "help me prepare for", "study plan for", "plan the goal",
    "help me finish my", "orchestrate task", "create a study plan"
]

SMART_CLICK_TRIGGERS = [
    "click on",
    "find and click",
    "where is the",
    "what's at",
    "what is at",
    "locate the",
]

OPEN_FOLDER_WORDS = ["open folder", "go to folder", "navigate to"]

WHATSAPP_SEND_WORDS = ["send screenshot", "share screenshot", "send the screenshot", "whatsapp screenshot", "send screen"]
WHATSAPP_MESSAGE_WORDS = ["send whatsapp", "whatsapp message"]

WINDOWS_OPEN_WORDS = ["what windows are open", "show open windows", "list windows", "what's open"]
PRESS_KEY_WORDS = ["press "]

PRODUCT_CHEAPEST_WORDS = ["cheapest", "lowest price", "least expensive"]

MINIMIZE_WORDS = ["minimize"]
MAXIMIZE_WORDS = ["maximize"]

LEARN_FACE_WORDS = ["my name is ", "enroll me as ", "register face as ", "save my face as ", "learn my face as "]
LEARN_FACE_INTRO_WORDS = ["i am ", "i'm ", "im "]
LEARN_OBJECT_WORDS = ["learn this as ", "learn object ", "learn this object as "]

TEACH_COMMAND_WORDS = ["learn this command", "new command", "add command", "teach you a command", "teach you new", "custom command"]

PLAYWRIGHT_PLAN_WORDS = ["plan ", "automate ", "run task ", "start agent "]
PLAYWRIGHT_CLOSE_WORDS = ["close browser", "exit browser"]
PLAYWRIGHT_OPEN_WORDS = ["open browser", "start browser", "launch browser"]
PLAYWRIGHT_GO_TO_WORDS = ["go to ", "navigate to "]
PLAYWRIGHT_AMAZON_WORDS = ["search amazon for ", "amazon search "]
PLAYWRIGHT_YOUTUBE_WORDS = ["search youtube for ", "youtube search "]
PLAYWRIGHT_FIRST_RESULT_WORDS = ["open first result", "click first result", "play first video", "select first product", "first link", "first result", "first video", "first product", "first item", "number one", "first one"]
PLAYWRIGHT_ADD_CART_WORDS = ["add to cart", "click add to cart"]
PLAYWRIGHT_FILL_WORDS = ["fill ", " with ", "type ", " in ", "enter "]
PLAYWRIGHT_SUMMARIZE_WORDS = ["summarize this page", "summarize the page", "summarize page", "summarize website", "summarize webpage", "what is on this page"]

ROOM_LEARN_TRIGGERS = ["learn this room as ", "learn this environment as ", "this room is ", "this environment is ", "associate this room with "]
ROOM_QUERY_TRIGGERS = ["where am i", "what room is this", "what room am i in", "which room is this", "identify this room", "where am i right now", "do you know where i am", "recognize this room"]
OBJECT_IDENTIFY_TRIGGERS = ["holding", "person is holding", "person holding", "he is holding", "she is holding", "they are holding", "in his hand", "in her hand", "in their hand", "what is in front of me", "what is in my hand", "what am i holding", "what is this", "what is tihis", "what's this", "identify this", "identfy this", "idenfty this", "what do you see", "what is in the room", "whats in the room", "what's in the room", "whats around you", "what's around you", "what is around you", "what do you see around you", "what is around", "whats around", "what's around", "what is in front of you"]

DISABLE_AR_WORDS = [
    "disable ar playground", "ar playground off", "stop ar mode", "ar mode off",
    "stop ar playground", "disable ar mode",
    "disable air playground", "air playground off", "stop air mode", "air mode off",
    "stop air playground", "disable air mode",
    "stop ar object", "disable ar object", "stop ar whiteboard", "disable ar whiteboard",
    "stop ar face", "disable ar face", "stop ar drawing", "disable ar drawing",
    "stop ar physics", "disable ar physics", "stop ar pose", "disable ar pose",
    "stop ar pet", "disable ar pet", "stop ar flower", "disable ar flower",
    "stop ar piano", "disable ar piano", "stop ar wand", "disable ar wand",
    "close camera", "stop camera", "turn off camera", "hide camera", "camera off",
    "disable object mode", "stop object mode", "close object mode", "object mode off",
    "disable face mode", "stop face mode", "close face mode", "face mode off",
    "disable person mode", "stop person mode", "close person mode", "person mode off",
    "close the object one", "disable the object one", "stop the object one",
    "disable ar 3d", "disable ar3d", "disable ar3d mode", "disable ar mode", "disable ar",
    "close ar 3d", "close ar3d", "close ar3d mode", "close ar mode", "close ar",
    "exit ar 3d", "exit ar3d", "exit ar3d mode", "exit ar mode", "exit ar",
    "stop ar 3d", "stop ar3d", "stop ar3d mode", "stop ar",
    "turn off ar 3d", "turn off ar3d", "turn off ar3d mode", "turn off ar",
    "shutdown ar 3d", "shutdown ar3d", "shutdown ar3d mode", "shutdown ar"
]

FACE_ID_TRIGGERS = [
    "who is around", "who are around", "who is in the room", "who is there", "who do you see", 
    "is there anyone", "is anyone there", "who is around you", "who is around me", 
    "who's around", "who around", "who is near", "who is near me", "who is near you",
    "who is in the space", "anyone around", "anyone in the room"
]

CAMERA_OPEN_TRIGGERS = [
    "show camera", "open camera", "turn on camera", "vision mode",
    "open opencv", "open cv", "start camera", "camera on",
    "show objects", "show you objects", "show me objects",
    "learn objects", "teach you objects", "i will show you",
    "visual mode", "visual input", "visual data",
    "look at this", "look at me", "i want to show you",
    "object learning", "object recognition",
    "new object", "what is this", "what is tihis",
]

OBJECT_LIST_WORDS = ["what do you know", "list objects", "what have you learned", "what objects do you know"]

ALWAYS_LISTEN_WORDS = ["always listen", "continuous mode"]
STOP_LISTEN_WORDS = ["stop listening", "wake word mode", "hey aria mode"]

LANGUAGE_HINDI_WORDS = ["switch to hindi", "change language to hindi", "hindi language mode"]
LANGUAGE_TELUGU_WORDS = ["switch to telugu", "change language to telugu", "telugu language mode"]
LANGUAGE_ENGLISH_WORDS = ["switch to english", "change language to english", "english language mode"]
LANGUAGE_AUTO_WORDS = ["auto language mode", "switch to auto language", "disable language lock", "automatic language mode"]

GESTURE_DISABLE_WORDS = ["disable gesture control", "gesture mode off", "stop gesture control", "hand gesture off", "disable hand tracking", "stop hand tracking"]
GESTURE_ENABLE_WORDS = ["enable gesture control", "gesture mode on", "gesture mode", "hand gesture mode", "start gesture control", "gesture control on", "hand tracking mode", "enable hand tracking", "gesture control"]

AR_SUBCOMMAND_WORDS = [
    "clear board", "clear canvas", "clear whiteboard", "undo", "next mask", "change mask",
    "previous mask", "prev mask", "remember this", "save this", "create a", "create an", "generate a",
    "show me a", "load a", "make a", "load the", "show me the model", "show the model", "show me the",
    "load model", "display the", "put up the", "put the", "is the model ready", "is the 3d model ready", "model ready",
    "rotate left", "rotate right", "rotate up", "rotate down", "make it bigger", "make it smaller", "zoom in", "zoom out",
    "reset view", "show wireframe", "explode model", "explode it", "change color", "change colour",
    "move", "rotate", "make", "reset", "center", "show controls", "controls"
]

AR_MODE_TRIGGERS = {
    "wand": ["ar wand", "ar magic", "ar trail", "air wand", "air magic", "air trail"],
    "flowers": ["ar flower", "ar garden", "air flower", "air garden"],
    "piano": ["ar piano", "ar synth", "ar music", "air piano", "air synth", "air music"],
    "pet": ["ar pet", "ar cat", "air pet", "air cat"],
    "drawing": ["ar drawing", "ar canvas", "air drawing", "air canvas"],
    "physics": ["ar physics", "ar ball", "air physics", "air ball"],
    "face": ["ar face", "ar mask", "air face", "air mask"],
    "pose": ["ar pose", "ar body", "air pose", "air body"],
    "whiteboard": ["ar whiteboard", "ar write", "air whiteboard", "air write"],
    "object": ["ar object", "ar interact", "air object", "air interact"],
    "ar3d": ["ar 3d mode", "enable ar 3d", "enable ar3d", "3d mode on", "ar hologram mode", "hologram mode", "ar 3d", "ar3d model", "enable ar3d model", "ar3d", "air 3d", "enable air 3d"]
}

AR_ACTIVE_ONLY_TRIGGERS = {
    "wand": ["wand mode", "magic mode", "trail mode"],
    "flowers": ["flower mode", "garden mode"],
    "piano": ["piano mode", "synth mode", "music mode"],
    "pet": ["pet mode", "cat mode"],
    "drawing": ["drawing mode", "canvas mode"],
    "physics": ["physics mode", "balls mode", "ball mode"],
    "face": ["face mode", "mask mode"],
    "pose": ["pose mode", "body mode"],
    "whiteboard": ["whiteboard mode", "write mode"],
    "object": ["object mode", "interact mode"],
    "ar3d": ["3d mode", "hologram mode", "ar3d mode", "ar3d"]
}

FEEDBACK_NEGATIVE_WORDS = [
    "stop", "quiet", "shut up", "be quiet", "don't talk", 
    "no suggestions", "go away", "ignore", "annoying", "mute", "dismiss"
]

FEEDBACK_POSITIVE_WORDS = [
    "thanks", "thank you", "sure", "yes", "do it", 
    "do that", "okay", "ok", "helpful", "cool", "i will"
]
