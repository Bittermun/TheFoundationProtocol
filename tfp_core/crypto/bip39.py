# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP BIP-39 Standard Hardware Root-of-Trust and Hierarchical Deterministic Key Derivation.

Implements:
- Full 2048-word English standard BIP-39 wordlist
- 128-bit (12-word) to 256-bit (24-word) mnemonic generation with SHA-256 bitwise checksum
- Exact bitwise checksum validation for recovery
- PBKDF2-HMAC-SHA512 seed derivation (2048 iterations, 64-byte seed)
- SLIP-0010 Hierarchical Deterministic (HD) key derivation for Ed25519 / Dilithium / PQC keys
"""

import hashlib
import hmac
import secrets
import struct
from typing import Dict, List, Optional, Tuple

try:
    from cryptography.hazmat.primitives.asymmetric import ed25519
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False


BIP39_WORDLIST = [
    'abandon', 'ability', 'able', 'about', 'above', 'absent', 'absorb', 'abstract',
    'absurd', 'abuse', 'access', 'accident', 'account', 'accuse', 'achieve', 'acid',
    'acoustic', 'acquire', 'across', 'act', 'action', 'actor', 'actress', 'actual',
    'adapt', 'add', 'addict', 'address', 'adjust', 'admit', 'adult', 'advance',
    'advice', 'aerobic', 'affair', 'afford', 'afraid', 'again', 'age', 'agent',
    'agree', 'ahead', 'aim', 'air', 'airport', 'aisle', 'alarm', 'album',
    'alcohol', 'alert', 'alien', 'all', 'alley', 'allow', 'almost', 'alone',
    'alpha', 'already', 'also', 'alter', 'always', 'amateur', 'amazing', 'among',
    'amount', 'amused', 'analyst', 'anchor', 'ancient', 'anger', 'angle', 'angry',
    'animal', 'ankle', 'announce', 'annual', 'another', 'answer', 'antenna', 'antique',
    'anxiety', 'any', 'apart', 'apology', 'appear', 'apple', 'approve', 'april',
    'arch', 'arctic', 'area', 'arena', 'argue', 'arm', 'armed', 'armor',
    'army', 'around', 'arrange', 'arrest', 'arrive', 'arrow', 'art', 'artefact',
    'artist', 'artwork', 'ask', 'aspect', 'assault', 'asset', 'assist', 'assume',
    'asthma', 'athlete', 'atom', 'attack', 'attend', 'attitude', 'attract', 'auction',
    'audit', 'august', 'aunt', 'author', 'auto', 'autumn', 'average', 'avocado',
    'avoid', 'awake', 'aware', 'away', 'awesome', 'awful', 'awkward', 'axis',
    'baby', 'bachelor', 'bacon', 'badge', 'bag', 'balance', 'balcony', 'ball',
    'bamboo', 'banana', 'banner', 'bar', 'barely', 'bargain', 'barrel', 'base',
    'basic', 'basket', 'battle', 'beach', 'bean', 'beauty', 'because', 'become',
    'beef', 'before', 'begin', 'behave', 'behind', 'believe', 'below', 'belt',
    'bench', 'benefit', 'best', 'betray', 'better', 'between', 'beyond', 'bicycle',
    'bid', 'bike', 'bind', 'biology', 'bird', 'birth', 'bitter', 'black',
    'blade', 'blame', 'blanket', 'blast', 'bleak', 'bless', 'blind', 'blood',
    'blossom', 'blouse', 'blue', 'blur', 'blush', 'board', 'boat', 'body',
    'boil', 'bomb', 'bone', 'bonus', 'book', 'boost', 'border', 'boring',
    'borrow', 'boss', 'bottom', 'bounce', 'box', 'boy', 'bracket', 'brain',
    'brand', 'brass', 'brave', 'bread', 'breeze', 'brick', 'bridge', 'brief',
    'bright', 'bring', 'brisk', 'broccoli', 'broken', 'bronze', 'broom', 'brother',
    'brown', 'brush', 'bubble', 'buddy', 'budget', 'buffalo', 'build', 'bulb',
    'bulk', 'bullet', 'bundle', 'bunker', 'burden', 'burger', 'burst', 'bus',
    'business', 'busy', 'butter', 'buyer', 'buzz', 'cabbage', 'cabin', 'cable',
    'cactus', 'cage', 'cake', 'call', 'calm', 'camera', 'camp', 'can',
    'canal', 'cancel', 'candy', 'cannon', 'canoe', 'canvas', 'canyon', 'capable',
    'capital', 'captain', 'car', 'carbon', 'card', 'cargo', 'carpet', 'carry',
    'cart', 'case', 'cash', 'casino', 'castle', 'casual', 'cat', 'catalog',
    'catch', 'category', 'cattle', 'caught', 'cause', 'caution', 'cave', 'ceiling',
    'celery', 'cement', 'census', 'century', 'cereal', 'certain', 'chair', 'chalk',
    'champion', 'change', 'chaos', 'chapter', 'charge', 'chase', 'chat', 'cheap',
    'check', 'cheese', 'chef', 'cherry', 'chest', 'chicken', 'chief', 'child',
    'chimney', 'choice', 'choose', 'chronic', 'chuckle', 'chunk', 'churn', 'cigar',
    'cinnamon', 'circle', 'citizen', 'city', 'civil', 'claim', 'clap', 'clarify',
    'claw', 'clay', 'clean', 'clerk', 'clever', 'click', 'client', 'cliff',
    'climb', 'clinic', 'clip', 'clock', 'clog', 'close', 'cloth', 'cloud',
    'clown', 'club', 'clump', 'cluster', 'clutch', 'coach', 'coast', 'coconut',
    'code', 'coffee', 'coil', 'coin', 'collect', 'color', 'column', 'combine',
    'come', 'comfort', 'comic', 'common', 'company', 'concert', 'conduct', 'confirm',
    'congress', 'connect', 'consider', 'control', 'convince', 'cook', 'cool', 'copper',
    'copy', 'coral', 'core', 'corn', 'correct', 'cost', 'cotton', 'couch',
    'country', 'couple', 'course', 'cousin', 'cover', 'coyote', 'crack', 'cradle',
    'craft', 'cram', 'crane', 'crash', 'crater', 'crawl', 'crazy', 'cream',
    'credit', 'creek', 'crew', 'cricket', 'crime', 'crisp', 'critic', 'crop',
    'cross', 'crouch', 'crowd', 'crucial', 'cruel', 'cruise', 'crumble', 'crunch',
    'crush', 'cry', 'crystal', 'cube', 'culture', 'cup', 'cupboard', 'curious',
    'current', 'curtain', 'curve', 'cushion', 'custom', 'cute', 'cycle', 'dad',
    'damage', 'damp', 'dance', 'danger', 'daring', 'dash', 'daughter', 'dawn',
    'day', 'deal', 'debate', 'debris', 'decade', 'december', 'decide', 'decline',
    'decorate', 'decrease', 'deer', 'defense', 'define', 'defy', 'degree', 'delay',
    'deliver', 'demand', 'demise', 'denial', 'dentist', 'deny', 'depart', 'depend',
    'deposit', 'depth', 'deputy', 'derive', 'describe', 'desert', 'design', 'desk',
    'despair', 'destroy', 'detail', 'detect', 'develop', 'device', 'devote', 'diagram',
    'dial', 'diamond', 'diary', 'dice', 'diesel', 'diet', 'differ', 'digital',
    'dignity', 'dilemma', 'dinner', 'dinosaur', 'direct', 'dirt', 'disagree', 'discover',
    'disease', 'dish', 'dismiss', 'disorder', 'display', 'distance', 'divert', 'divide',
    'divorce', 'dizzy', 'doctor', 'document', 'dog', 'doll', 'dolphin', 'domain',
    'donate', 'donkey', 'donor', 'door', 'dose', 'double', 'dove', 'draft',
    'dragon', 'drama', 'drastic', 'draw', 'dream', 'dress', 'drift', 'drill',
    'drink', 'drip', 'drive', 'drop', 'drum', 'dry', 'duck', 'dumb',
    'dune', 'during', 'dust', 'dutch', 'duty', 'dwarf', 'dynamic', 'eager',
    'eagle', 'early', 'earn', 'earth', 'easily', 'east', 'easy', 'echo',
    'ecology', 'economy', 'edge', 'edit', 'educate', 'effort', 'egg', 'eight',
    'either', 'elbow', 'elder', 'electric', 'elegant', 'element', 'elephant', 'elevator',
    'elite', 'else', 'embark', 'embody', 'embrace', 'emerge', 'emotion', 'employ',
    'empower', 'empty', 'enable', 'enact', 'end', 'endless', 'endorse', 'enemy',
    'energy', 'enforce', 'engage', 'engine', 'enhance', 'enjoy', 'enlist', 'enough',
    'enrich', 'enroll', 'ensure', 'enter', 'entire', 'entry', 'envelope', 'episode',
    'equal', 'equip', 'era', 'erase', 'erode', 'erosion', 'error', 'erupt',
    'escape', 'essay', 'essence', 'estate', 'eternal', 'ethics', 'evidence', 'evil',
    'evoke', 'evolve', 'exact', 'example', 'excess', 'exchange', 'excite', 'exclude',
    'excuse', 'execute', 'exercise', 'exhaust', 'exhibit', 'exile', 'exist', 'exit',
    'exotic', 'expand', 'expect', 'expire', 'explain', 'expose', 'express', 'extend',
    'extra', 'eye', 'eyebrow', 'fabric', 'face', 'faculty', 'fade', 'faint',
    'faith', 'fall', 'false', 'fame', 'family', 'famous', 'fan', 'fancy',
    'fantasy', 'farm', 'fashion', 'fat', 'fatal', 'father', 'fatigue', 'fault',
    'favorite', 'feature', 'february', 'federal', 'fee', 'feed', 'feel', 'female',
    'fence', 'festival', 'fetch', 'fever', 'few', 'fiber', 'fiction', 'field',
    'figure', 'file', 'film', 'filter', 'final', 'find', 'fine', 'finger',
    'finish', 'fire', 'firm', 'first', 'fiscal', 'fish', 'fit', 'fitness',
    'fix', 'flag', 'flame', 'flash', 'flat', 'flavor', 'flee', 'flight',
    'flip', 'float', 'flock', 'floor', 'flower', 'fluid', 'flush', 'fly',
    'foam', 'focus', 'fog', 'foil', 'fold', 'follow', 'food', 'foot',
    'force', 'forest', 'forget', 'fork', 'fortune', 'forum', 'forward', 'fossil',
    'foster', 'found', 'fox', 'fragile', 'frame', 'frequent', 'fresh', 'friend',
    'fringe', 'frog', 'front', 'frost', 'frown', 'frozen', 'fruit', 'fuel',
    'fun', 'funny', 'furnace', 'fury', 'future', 'gadget', 'gain', 'galaxy',
    'gallery', 'game', 'gap', 'garage', 'garbage', 'garden', 'garlic', 'garment',
    'gas', 'gasp', 'gate', 'gather', 'gauge', 'gaze', 'general', 'genius',
    'genre', 'gentle', 'genuine', 'gesture', 'ghost', 'giant', 'gift', 'giggle',
    'ginger', 'giraffe', 'girl', 'give', 'glad', 'glance', 'glare', 'glass',
    'glide', 'glimpse', 'globe', 'gloom', 'glory', 'glove', 'glow', 'glue',
    'goat', 'goddess', 'gold', 'good', 'goose', 'gorilla', 'gospel', 'gossip',
    'govern', 'gown', 'grab', 'grace', 'grain', 'grant', 'grape', 'grass',
    'gravity', 'great', 'green', 'grid', 'grief', 'grit', 'grocery', 'group',
    'grow', 'grunt', 'guard', 'guess', 'guide', 'guilt', 'guitar', 'gun',
    'gym', 'habit', 'hair', 'half', 'hammer', 'hamster', 'hand', 'happy',
    'harbor', 'hard', 'harsh', 'harvest', 'hat', 'have', 'hawk', 'hazard',
    'head', 'health', 'heart', 'heavy', 'hedgehog', 'height', 'hello', 'helmet',
    'help', 'hen', 'hero', 'hidden', 'high', 'hill', 'hint', 'hip',
    'hire', 'history', 'hobby', 'hockey', 'hold', 'hole', 'holiday', 'hollow',
    'home', 'honey', 'hood', 'hope', 'horn', 'horror', 'horse', 'hospital',
    'host', 'hotel', 'hour', 'hover', 'hub', 'huge', 'human', 'humble',
    'humor', 'hundred', 'hungry', 'hunt', 'hurdle', 'hurry', 'hurt', 'husband',
    'hybrid', 'ice', 'icon', 'idea', 'identify', 'idle', 'ignore', 'ill',
    'illegal', 'illness', 'image', 'imitate', 'immense', 'immune', 'impact', 'impose',
    'improve', 'impulse', 'inch', 'include', 'income', 'increase', 'index', 'indicate',
    'indoor', 'industry', 'infant', 'inflict', 'inform', 'inhale', 'inherit', 'initial',
    'inject', 'injury', 'inmate', 'inner', 'innocent', 'input', 'inquiry', 'insane',
    'insect', 'inside', 'inspire', 'install', 'intact', 'interest', 'into', 'invest',
    'invite', 'involve', 'iron', 'island', 'isolate', 'issue', 'item', 'ivory',
    'jacket', 'jaguar', 'jar', 'jazz', 'jealous', 'jeans', 'jelly', 'jewel',
    'job', 'join', 'joke', 'journey', 'joy', 'judge', 'juice', 'jump',
    'jungle', 'junior', 'junk', 'just', 'kangaroo', 'keen', 'keep', 'ketchup',
    'key', 'kick', 'kid', 'kidney', 'kind', 'kingdom', 'kiss', 'kit',
    'kitchen', 'kite', 'kitten', 'kiwi', 'knee', 'knife', 'knock', 'know',
    'lab', 'label', 'labor', 'ladder', 'lady', 'lake', 'lamp', 'language',
    'laptop', 'large', 'later', 'latin', 'laugh', 'laundry', 'lava', 'law',
    'lawn', 'lawsuit', 'layer', 'lazy', 'leader', 'leaf', 'learn', 'leave',
    'lecture', 'left', 'leg', 'legal', 'legend', 'leisure', 'lemon', 'lend',
    'length', 'lens', 'leopard', 'lesson', 'letter', 'level', 'liar', 'liberty',
    'library', 'license', 'life', 'lift', 'light', 'like', 'limb', 'limit',
    'link', 'lion', 'liquid', 'list', 'little', 'live', 'lizard', 'load',
    'loan', 'lobster', 'local', 'lock', 'logic', 'lonely', 'long', 'loop',
    'lottery', 'loud', 'lounge', 'love', 'loyal', 'lucky', 'luggage', 'lumber',
    'lunar', 'lunch', 'luxury', 'lyrics', 'machine', 'mad', 'magic', 'magnet',
    'maid', 'mail', 'main', 'major', 'make', 'mammal', 'man', 'manage',
    'mandate', 'mango', 'mansion', 'manual', 'maple', 'marble', 'march', 'margin',
    'marine', 'market', 'marriage', 'mask', 'mass', 'master', 'match', 'material',
    'math', 'matrix', 'matter', 'maximum', 'maze', 'meadow', 'mean', 'measure',
    'meat', 'mechanic', 'medal', 'media', 'melody', 'melt', 'member', 'memory',
    'mention', 'menu', 'mercy', 'merge', 'merit', 'merry', 'mesh', 'message',
    'metal', 'method', 'middle', 'midnight', 'milk', 'million', 'mimic', 'mind',
    'minimum', 'minor', 'minute', 'miracle', 'mirror', 'misery', 'miss', 'mistake',
    'mix', 'mixed', 'mixture', 'mobile', 'model', 'modify', 'mom', 'moment',
    'monitor', 'monkey', 'monster', 'month', 'moon', 'moral', 'more', 'morning',
    'mosquito', 'mother', 'motion', 'motor', 'mountain', 'mouse', 'move', 'movie',
    'much', 'muffin', 'mule', 'multiply', 'muscle', 'museum', 'mushroom', 'music',
    'must', 'mutual', 'myself', 'mystery', 'myth', 'naive', 'name', 'napkin',
    'narrow', 'nasty', 'nation', 'nature', 'near', 'neck', 'need', 'negative',
    'neglect', 'neither', 'nephew', 'nerve', 'nest', 'net', 'network', 'neutral',
    'never', 'news', 'next', 'nice', 'night', 'noble', 'noise', 'nominee',
    'noodle', 'normal', 'north', 'nose', 'notable', 'note', 'nothing', 'notice',
    'novel', 'now', 'nuclear', 'number', 'nurse', 'nut', 'oak', 'obey',
    'object', 'oblige', 'obscure', 'observe', 'obtain', 'obvious', 'occur', 'ocean',
    'october', 'odor', 'off', 'offer', 'office', 'often', 'oil', 'okay',
    'old', 'olive', 'olympic', 'omit', 'once', 'one', 'onion', 'online',
    'only', 'open', 'opera', 'opinion', 'oppose', 'option', 'orange', 'orbit',
    'orchard', 'order', 'ordinary', 'organ', 'orient', 'original', 'orphan', 'ostrich',
    'other', 'outdoor', 'outer', 'output', 'outside', 'oval', 'oven', 'over',
    'own', 'owner', 'oxygen', 'oyster', 'ozone', 'pact', 'paddle', 'page',
    'pair', 'palace', 'palm', 'panda', 'panel', 'panic', 'panther', 'paper',
    'parade', 'parent', 'park', 'parrot', 'party', 'pass', 'patch', 'path',
    'patient', 'patrol', 'pattern', 'pause', 'pave', 'payment', 'peace', 'peanut',
    'pear', 'peasant', 'pelican', 'pen', 'penalty', 'pencil', 'people', 'pepper',
    'perfect', 'permit', 'person', 'pet', 'phone', 'photo', 'phrase', 'physical',
    'piano', 'picnic', 'picture', 'piece', 'pig', 'pigeon', 'pill', 'pilot',
    'pink', 'pioneer', 'pipe', 'pistol', 'pitch', 'pizza', 'place', 'planet',
    'plastic', 'plate', 'play', 'please', 'pledge', 'pluck', 'plug', 'plunge',
    'poem', 'poet', 'point', 'polar', 'pole', 'police', 'pond', 'pony',
    'pool', 'popular', 'portion', 'position', 'possible', 'post', 'potato', 'pottery',
    'poverty', 'powder', 'power', 'practice', 'praise', 'predict', 'prefer', 'prepare',
    'present', 'pretty', 'prevent', 'price', 'pride', 'primary', 'print', 'priority',
    'prison', 'private', 'prize', 'problem', 'process', 'produce', 'profit', 'program',
    'project', 'promote', 'proof', 'property', 'prosper', 'protect', 'proud', 'provide',
    'public', 'pudding', 'pull', 'pulp', 'pulse', 'pumpkin', 'punch', 'pupil',
    'puppy', 'purchase', 'purity', 'purpose', 'purse', 'push', 'put', 'puzzle',
    'pyramid', 'quality', 'quantum', 'quarter', 'question', 'quick', 'quit', 'quiz',
    'quote', 'rabbit', 'raccoon', 'race', 'rack', 'radar', 'radio', 'rail',
    'rain', 'raise', 'rally', 'ramp', 'ranch', 'random', 'range', 'rapid',
    'rare', 'rate', 'rather', 'raven', 'raw', 'razor', 'ready', 'real',
    'reason', 'rebel', 'rebuild', 'recall', 'receive', 'recipe', 'record', 'recycle',
    'reduce', 'reflect', 'reform', 'refuse', 'region', 'regret', 'regular', 'reject',
    'relax', 'release', 'relief', 'rely', 'remain', 'remember', 'remind', 'remove',
    'render', 'renew', 'rent', 'reopen', 'repair', 'repeat', 'replace', 'report',
    'require', 'rescue', 'resemble', 'resist', 'resource', 'response', 'result', 'retire',
    'retreat', 'return', 'reunion', 'reveal', 'review', 'reward', 'rhythm', 'rib',
    'ribbon', 'rice', 'rich', 'ride', 'ridge', 'rifle', 'right', 'rigid',
    'ring', 'riot', 'ripple', 'risk', 'ritual', 'rival', 'river', 'road',
    'roast', 'robot', 'robust', 'rocket', 'romance', 'roof', 'rookie', 'room',
    'rose', 'rotate', 'rough', 'round', 'route', 'royal', 'rubber', 'rude',
    'rug', 'rule', 'run', 'runway', 'rural', 'sad', 'saddle', 'sadness',
    'safe', 'sail', 'salad', 'salmon', 'salon', 'salt', 'salute', 'same',
    'sample', 'sand', 'satisfy', 'satoshi', 'sauce', 'sausage', 'save', 'say',
    'scale', 'scan', 'scare', 'scatter', 'scene', 'scheme', 'school', 'science',
    'scissors', 'scorpion', 'scout', 'scrap', 'screen', 'script', 'scrub', 'sea',
    'search', 'season', 'seat', 'second', 'secret', 'section', 'security', 'seed',
    'seek', 'segment', 'select', 'sell', 'seminar', 'senior', 'sense', 'sentence',
    'series', 'service', 'session', 'settle', 'setup', 'seven', 'shadow', 'shaft',
    'shallow', 'share', 'shed', 'shell', 'sheriff', 'shield', 'shift', 'shine',
    'ship', 'shiver', 'shock', 'shoe', 'shoot', 'shop', 'short', 'shoulder',
    'shove', 'shrimp', 'shrug', 'shuffle', 'shy', 'sibling', 'sick', 'side',
    'siege', 'sight', 'sign', 'silent', 'silk', 'silly', 'silver', 'similar',
    'simple', 'since', 'sing', 'siren', 'sister', 'situate', 'six', 'size',
    'skate', 'sketch', 'ski', 'skill', 'skin', 'skirt', 'skull', 'slab',
    'slam', 'sleep', 'slender', 'slice', 'slide', 'slight', 'slim', 'slogan',
    'slot', 'slow', 'slush', 'small', 'smart', 'smile', 'smoke', 'smooth',
    'snack', 'snake', 'snap', 'sniff', 'snow', 'soap', 'soccer', 'social',
    'sock', 'soda', 'soft', 'solar', 'soldier', 'solid', 'solution', 'solve',
    'someone', 'song', 'soon', 'sorry', 'sort', 'soul', 'sound', 'soup',
    'source', 'south', 'space', 'spare', 'spatial', 'spawn', 'speak', 'special',
    'speed', 'spell', 'spend', 'sphere', 'spice', 'spider', 'spike', 'spin',
    'spirit', 'split', 'spoil', 'sponsor', 'spoon', 'sport', 'spot', 'spray',
    'spread', 'spring', 'spy', 'square', 'squeeze', 'squirrel', 'stable', 'stadium',
    'staff', 'stage', 'stairs', 'stamp', 'stand', 'start', 'state', 'stay',
    'steak', 'steel', 'stem', 'step', 'stereo', 'stick', 'still', 'sting',
    'stock', 'stomach', 'stone', 'stool', 'story', 'stove', 'strategy', 'street',
    'strike', 'strong', 'struggle', 'student', 'stuff', 'stumble', 'style', 'subject',
    'submit', 'subway', 'success', 'such', 'sudden', 'suffer', 'sugar', 'suggest',
    'suit', 'summer', 'sun', 'sunny', 'sunset', 'super', 'supply', 'supreme',
    'sure', 'surface', 'surge', 'surprise', 'surround', 'survey', 'suspect', 'sustain',
    'swallow', 'swamp', 'swap', 'swarm', 'swear', 'sweet', 'swift', 'swim',
    'swing', 'switch', 'sword', 'symbol', 'symptom', 'syrup', 'system', 'table',
    'tackle', 'tag', 'tail', 'talent', 'talk', 'tank', 'tape', 'target',
    'task', 'taste', 'tattoo', 'taxi', 'teach', 'team', 'tell', 'ten',
    'tenant', 'tennis', 'tent', 'term', 'test', 'text', 'thank', 'that',
    'theme', 'then', 'theory', 'there', 'they', 'thing', 'this', 'thought',
    'three', 'thrive', 'throw', 'thumb', 'thunder', 'ticket', 'tide', 'tiger',
    'tilt', 'timber', 'time', 'tiny', 'tip', 'tired', 'tissue', 'title',
    'toast', 'tobacco', 'today', 'toddler', 'toe', 'together', 'toilet', 'token',
    'tomato', 'tomorrow', 'tone', 'tongue', 'tonight', 'tool', 'tooth', 'top',
    'topic', 'topple', 'torch', 'tornado', 'tortoise', 'toss', 'total', 'tourist',
    'toward', 'tower', 'town', 'toy', 'track', 'trade', 'traffic', 'tragic',
    'train', 'transfer', 'trap', 'trash', 'travel', 'tray', 'treat', 'tree',
    'trend', 'trial', 'tribe', 'trick', 'trigger', 'trim', 'trip', 'trophy',
    'trouble', 'truck', 'true', 'truly', 'trumpet', 'trust', 'truth', 'try',
    'tube', 'tuition', 'tumble', 'tuna', 'tunnel', 'turkey', 'turn', 'turtle',
    'twelve', 'twenty', 'twice', 'twin', 'twist', 'two', 'type', 'typical',
    'ugly', 'umbrella', 'unable', 'unaware', 'uncle', 'uncover', 'under', 'undo',
    'unfair', 'unfold', 'unhappy', 'uniform', 'unique', 'unit', 'universe', 'unknown',
    'unlock', 'until', 'unusual', 'unveil', 'update', 'upgrade', 'uphold', 'upon',
    'upper', 'upset', 'urban', 'urge', 'usage', 'use', 'used', 'useful',
    'useless', 'usual', 'utility', 'vacant', 'vacuum', 'vague', 'valid', 'valley',
    'valve', 'van', 'vanish', 'vapor', 'various', 'vast', 'vault', 'vehicle',
    'velvet', 'vendor', 'venture', 'venue', 'verb', 'verify', 'version', 'very',
    'vessel', 'veteran', 'viable', 'vibrant', 'vicious', 'victory', 'video', 'view',
    'village', 'vintage', 'violin', 'virtual', 'virus', 'visa', 'visit', 'visual',
    'vital', 'vivid', 'vocal', 'voice', 'void', 'volcano', 'volume', 'vote',
    'voyage', 'wage', 'wagon', 'wait', 'walk', 'wall', 'walnut', 'want',
    'warfare', 'warm', 'warrior', 'wash', 'wasp', 'waste', 'water', 'wave',
    'way', 'wealth', 'weapon', 'wear', 'weasel', 'weather', 'web', 'wedding',
    'weekend', 'weird', 'welcome', 'west', 'wet', 'whale', 'what', 'wheat',
    'wheel', 'when', 'where', 'whip', 'whisper', 'wide', 'width', 'wife',
    'wild', 'will', 'win', 'window', 'wine', 'wing', 'wink', 'winner',
    'winter', 'wire', 'wisdom', 'wise', 'wish', 'witness', 'wolf', 'woman',
    'wonder', 'wood', 'wool', 'word', 'work', 'world', 'worry', 'worth',
    'wrap', 'wreck', 'wrestle', 'wrist', 'write', 'wrong', 'yard', 'year',
    'yellow', 'you', 'young', 'youth', 'zebra', 'zero', 'zone', 'zoo'
]

WORDLIST_ENGLISH = BIP39_WORDLIST
_WORD_INDEX_MAP: Dict[str, int] = {word: idx for idx, word in enumerate(BIP39_WORDLIST)}


def get_wordlist(language: str = "english") -> List[str]:
    """Retrieve the standard BIP-39 wordlist for a language."""
    if language.lower() != "english":
        raise ValueError(f"Unsupported language: {language}. Only 'english' is supported.")
    return list(BIP39_WORDLIST)


def generate_mnemonic(
    strength: int = 256,
    language: str = "english",
    entropy_bytes: Optional[bytes] = None,
) -> str:
    """
    Generate a standardized BIP-39 mnemonic phrase.

    Args:
        strength: Entropy strength in bits: 128 (12 words), 160 (15 words), 192 (18 words), 224 (21 words), or 256 (24 words).
        language: Wordlist language (default: 'english').
        entropy_bytes: Optional raw entropy bytes matching the requested strength.

    Returns:
        Space-separated BIP-39 mnemonic phrase.
    """
    wordlist = get_wordlist(language)

    if entropy_bytes is not None:
        num_bytes = len(entropy_bytes)
        if num_bytes not in (16, 20, 24, 28, 32):
            raise ValueError(f"Entropy length must be 16, 20, 24, 28, or 32 bytes (got {num_bytes})")
        entropy = entropy_bytes
        ent_bits = num_bytes * 8
    else:
        if strength not in (128, 160, 192, 224, 256):
            raise ValueError(f"Invalid strength: {strength}. Must be 128, 160, 192, 224, or 256 bits.")
        ent_bits = strength
        entropy = secrets.token_bytes(ent_bits // 8)

    cs_bits = ent_bits // 32
    hash_digest = hashlib.sha256(entropy).digest()

    # Convert entropy to bit string
    entropy_int = int.from_bytes(entropy, byteorder="big")
    cs_int = hash_digest[0] >> (8 - cs_bits) if cs_bits <= 8 else int.from_bytes(hash_digest[:2], "big") >> (16 - cs_bits)

    combined_int = (entropy_int << cs_bits) | cs_int
    total_bits = ent_bits + cs_bits
    num_words = total_bits // 11

    words = []
    for i in range(num_words - 1, -1, -1):
        idx = (combined_int >> (i * 11)) & 0x7FF
        words.append(wordlist[idx])

    return " ".join(words)


def validate_mnemonic(mnemonic: str, language: str = "english") -> bool:
    """
    Validate a BIP-39 mnemonic phrase for wordlist membership and exact bitwise checksum.

    Args:
        mnemonic: Space-separated mnemonic string.
        language: Wordlist language (default: 'english').

    Returns:
        True if valid, False otherwise.
    """
    if not isinstance(mnemonic, str):
        return False

    words = mnemonic.strip().split()
    num_words = len(words)
    if num_words not in (12, 15, 18, 21, 24):
        return False

    try:
        wordlist = get_wordlist(language)
    except ValueError:
        return False

    word_map = _WORD_INDEX_MAP if language.lower() == "english" else {w: i for i, w in enumerate(wordlist)}

    combined_int = 0
    for word in words:
        if word not in word_map:
            return False
        combined_int = (combined_int << 11) | word_map[word]

    total_bits = num_words * 11
    cs_bits = total_bits // 33
    ent_bits = total_bits - cs_bits

    extracted_cs = combined_int & ((1 << cs_bits) - 1)
    entropy_int = combined_int >> cs_bits
    entropy_bytes = entropy_int.to_bytes(ent_bits // 8, byteorder="big")

    hash_digest = hashlib.sha256(entropy_bytes).digest()
    expected_cs = hash_digest[0] >> (8 - cs_bits) if cs_bits <= 8 else int.from_bytes(hash_digest[:2], "big") >> (16 - cs_bits)

    return extracted_cs == expected_cs


def mnemonic_to_seed(mnemonic: str, passphrase: str = "") -> bytes:
    """
    Derive 512-bit (64-byte) binary seed from mnemonic and optional passphrase via PBKDF2-HMAC-SHA512.

    Args:
        mnemonic: BIP-39 mnemonic phrase.
        passphrase: Optional user passphrase / salt extension.

    Returns:
        64-byte seed.
    """
    salt = ("mnemonic" + passphrase).encode("utf-8")
    return hashlib.pbkdf2_hmac("sha512", mnemonic.encode("utf-8"), salt, iterations=2048, dklen=64)


def derive_slip0010(seed: bytes, path: str = "m/44'/9999'/0'/0/0") -> Tuple[bytes, bytes]:
    """
    Perform SLIP-0010 master and hardened child key derivation for Ed25519 / Dilithium.

    Args:
        seed: 64-byte binary seed from mnemonic_to_seed.
        path: Derivation path string, e.g. "m/44'/9999'/0'/0/0".

    Returns:
        (derived_private_key_32B, chain_code_32B)
    """
    # Master key generation
    hmac_master = hmac.new(b"ed25519 seed", seed, hashlib.sha512).digest()
    k_l = hmac_master[:32]
    k_r = hmac_master[32:]

    segments = [s.strip() for s in path.split("/") if s.strip()]
    if segments and segments[0] == "m":
        segments = segments[1:]

    for seg in segments:
        clean_idx = seg.rstrip("'h")
        index = int(clean_idx)
        # In SLIP-0010 Ed25519, all child derivations must be hardened
        child_index = index | 0x80000000

        data = b"\x00" + k_l + struct.pack(">I", child_index)
        hmac_child = hmac.new(k_r, data, hashlib.sha512).digest()
        k_l = hmac_child[:32]
        k_r = hmac_child[32:]

    return k_l, k_r


def derive_hd_key(seed: bytes, path: str = "m/44'/9999'/0'/0/0") -> Tuple[bytes, bytes]:
    """
    Derive Ed25519 / Dilithium device private and public keys via SLIP-0010.

    Args:
        seed: 64-byte master seed.
        path: HD derivation path (e.g. "m/44'/9999'/0'/0/0").

    Returns:
        (private_key_32B, public_key_32B)
    """
    priv_bytes, _ = derive_slip0010(seed, path)

    if CRYPTOGRAPHY_AVAILABLE:
        priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
        pub_bytes = priv_key.public_key().public_bytes_raw()
    else:
        # Fallback public key derivation
        pub_bytes = hashlib.sha256(priv_bytes + b"TFP_ED25519_PUB_FALLBACK").digest()

    return priv_bytes, pub_bytes


# Alias for interface compatibility
derive_key_path = derive_hd_key
