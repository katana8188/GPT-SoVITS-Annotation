import os,sys,re,json,LangSegment,shutil
import torch
import warnings
import site
import traceback
import logging
logging.getLogger("markdown_it").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("asyncio").setLevel(logging.ERROR)
logging.getLogger("charset_normalizer").setLevel(logging.ERROR)
logging.getLogger("torchaudio._extension").setLevel(logging.ERROR)
logging.getLogger("multipart.multipart").setLevel(logging.ERROR)
try:
    import gradio.analytics as analytics
    analytics.version_check = lambda :None
except:...
import gradio as gr
from scipy.io.wavfile import write
import subprocess

if len(sys.argv)==1:sys.argv.append("v2")
version="v1" if sys.argv[1]=="v1" else "v2"
os.environ["version"]=version
now_dir = os.getcwd()
sys.path.insert(0,now_dir)

warnings.filterwarnings("ignore")
tmp=os.path.join(now_dir,"TEMP")
os.makedirs(tmp,exist_ok=True)
os.environ["TEMP"]=tmp
if os.path.exists(tmp):
    for name in os.listdir(tmp):
        if name == "jieba.cache":
            continue
        path="%s/%s" % (tmp,name)
        delete = os.remove if os.path.isfile(path) else shutil.rmtree
        try:
            delete(path)
        except Exception as e:
            print(str(e))
            pass

output_dir= "生成记录"
os.makedirs(output_dir,exist_ok=True)
ref_dir = 'refwavs'
os.makedirs(ref_dir,exist_ok=True)

site_packages_roots = []
for path in site.getsitepackages():
    if "packages" in path:
        site_packages_roots.append(path)
if site_packages_roots==[]:
    site_packages_roots=["%s/runtime/Lib/site-packages" % now_dir]
for site_packages_root in site_packages_roots:
    if os.path.exists(site_packages_root):
        try:
            with open("%s/users.pth" % (site_packages_root), "w") as f:
                f.write(
                    "%s\n%s/tools\n%s/tools/asr\n%s/GPT_SoVITS\n%s/tools/uvr5"
                    % (now_dir, now_dir, now_dir, now_dir, now_dir)
                )
            # site.addsitedir(site_packages_root)
            break
        except PermissionError as e:
            traceback.print_exc()
from config import is_half,webui_port_infer_tts,is_share
from tools.i18n.i18n import I18nAuto,scan_language_list
language = sys.argv[-1] if sys.argv[-1] in scan_language_list() else "Auto"
os.environ["language"]=language
i18n = I18nAuto(language=language)


pretrained_sovits_name=["GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s2G2333k.pth", "GPT_SoVITS/pretrained_models/s2G488k.pth"]
pretrained_gpt_name=["GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt", "GPT_SoVITS/pretrained_models/s1bert25hz-2kh-longer-epoch=68e-step=50232.ckpt"]

SoVITS_weight_root = ["SoVITS_weights_v2","SoVITS_weights"]
GPT_weight_root = ["GPT_weights_v2","GPT_weights"]
for root in SoVITS_weight_root+GPT_weight_root:
    os.makedirs(root,exist_ok=True)

def get_weights_names():
    SoVITS_names = [name for name in pretrained_sovits_name]
    for path in SoVITS_weight_root:
        for name in os.listdir(path):
            if name.endswith(".pth"): SoVITS_names.append("%s/%s" % (path,name))
    GPT_names = [name for name in pretrained_gpt_name]
    for path in GPT_weight_root:
        for name in os.listdir(path):
            if name.endswith(".ckpt"): GPT_names.append("%s/%s" % (path,name))
    return SoVITS_names,GPT_names

SoVITS_names,GPT_names = get_weights_names()

def custom_sort_key(s):
    parts = re.split('(\d+)',s)
    parts = [int(part) if part.isdigit() else part for part in parts]
    return parts

def change_choices():
    SoVITS_names,GPT_names = get_weights_names()
    return {"choices": sorted(SoVITS_names,key=custom_sort_key),"__type__": "update"},{"choices":sorted(GPT_names,key=custom_sort_key),"__type__":"update"}

if os.path.exists(f"./weight.json"):
    pass
else:
    with open(f"./weight.json", 'w', encoding="utf-8") as file:json.dump({'GPT':{},'SoVITS':{}},file)

with open(f"./weight.json", 'r', encoding="utf-8") as file:
    weight_data = file.read()
    weight_data=json.loads(weight_data)
    gpt_path = weight_data.get('GPT',{}).get(version,pretrained_gpt_name)
    if not os.path.exists(gpt_path):
        gpt_path=pretrained_gpt_name
    sovits_path = weight_data.get('SoVITS',{}).get(version,pretrained_sovits_name)
    if not os.path.exists(sovits_path):
        sovits_path=pretrained_sovits_name
    if isinstance(gpt_path,list):
        gpt_path = gpt_path[0]
    if isinstance(sovits_path,list):
        sovits_path = sovits_path[0]

if os.path.exists(f"./GPT_SoVITS/hotwords.json"):
    pass
else:
    with open(f"./GPT_SoVITS/hotwords.json", 'w', encoding="utf-8") as file:json.dump({'':''},file)


infer_ttswebui = int(webui_port_infer_tts)
is_share = is_share
is_half = is_half and torch.cuda.is_available()
os.environ["no_proxy"] = "localhost, 127.0.0.1, ::1"
os.environ["all_proxy"] = ""
if torch.cuda.is_available():
    device = "cuda"
else:
    device = "cpu"

cnhubert_base_path = "GPT_SoVITS/pretrained_models/chinese-hubert-base"
bert_path = "GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large"

from transformers import AutoModelForMaskedLM,AutoTokenizer
import numpy as np
import librosa
from feature_extractor import cnhubert
from module.models import SynthesizerTrn
from AR.models.t2s_lightning_module import Text2SemanticLightningModule
from text import cleaned_text_to_sequence
from text.cleaner import clean_text
from time import time as ttime
from module.mel_processing import spectrogram_torch
from tools.my_utils import load_audio

cnhubert.cnhubert_base_path = cnhubert_base_path
tokenizer = AutoTokenizer.from_pretrained(bert_path)
bert_model = AutoModelForMaskedLM.from_pretrained(bert_path)
if is_half == True:
    bert_model = bert_model.half().to(device)
else:
    bert_model = bert_model.to(device)
ssl_model = cnhubert.get_model()
if is_half == True:
    ssl_model = ssl_model.half().to(device)
else:
    ssl_model = ssl_model.to(device)
punctuation = set(['!', '?', '…', ',', '.', '-'," "])
dict_language_v1 = {
    i18n("中文"): "all_zh",#全部按中文识别
    i18n("英文"): "en",#全部按英文识别#######不变
    i18n("日文"): "all_ja",#全部按日文识别
    i18n("中英混合"): "zh",#按中英混合识别####不变
    i18n("日英混合"): "ja",#按日英混合识别####不变
    i18n("多语种混合"): "auto",#多语种启动切分识别语种
}
dict_language_v2 = {
    i18n("中文"): "all_zh",#全部按中文识别
    i18n("英文"): "en",#全部按英文识别#######不变
    i18n("日文"): "all_ja",#全部按日文识别
    i18n("粤语"): "all_yue",#全部按中文识别
    i18n("韩文"): "all_ko",#全部按韩文识别
    i18n("中英混合"): "zh",#按中英混合识别####不变
    i18n("日英混合"): "ja",#按日英混合识别####不变
    i18n("粤英混合"): "yue",#按粤英混合识别####不变
    i18n("韩英混合"): "ko",#按韩英混合识别####不变
    i18n("多语种混合"): "auto",#多语种启动切分识别语种
    i18n("多语种混合(粤语)"): "auto_yue",#多语种启动切分识别语种
}
dict_language = dict_language_v1 if version =='v1' else dict_language_v2


def get_bert_feature(text, word2ph):
    with torch.no_grad():
        inputs = tokenizer(text, return_tensors="pt")
        for i in inputs:
            inputs[i] = inputs[i].to(device)
        res = bert_model(**inputs, output_hidden_states=True)
        res = torch.cat(res["hidden_states"][-3:-2], -1)[0].cpu()[1:-1]
    assert len(word2ph) == len(text)
    phone_level_feature = []
    for i in range(len(word2ph)):
        repeat_feature = res[i].repeat(word2ph[i], 1)
        phone_level_feature.append(repeat_feature)
    phone_level_feature = torch.cat(phone_level_feature, dim=0)
    return phone_level_feature.T

class DictToAttrRecursive(dict):
    def __init__(self, input_dict):
        super().__init__(input_dict)
        for key, value in input_dict.items():
            if isinstance(value, dict):
                value = DictToAttrRecursive(value)
            self[key] = value
            setattr(self, key, value)

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(f"Attribute {item} not found")

    def __setattr__(self, key, value):
        if isinstance(value, dict):
            value = DictToAttrRecursive(value)
        super(DictToAttrRecursive, self).__setitem__(key, value)
        super().__setattr__(key, value)

    def __delattr__(self, item):
        try:
            del self[item]
        except KeyError:
            raise AttributeError(f"Attribute {item} not found")

def change_sovits_weights(sovits_path,prompt_language=None,text_language=None):
    global vq_model, hps, version, dict_language
    dict_s2 = torch.load(sovits_path, map_location="cpu")
    hps = dict_s2["config"]
    hps = DictToAttrRecursive(hps)
    hps.model.semantic_frame_rate = "25hz"
    if dict_s2['weight']['enc_p.text_embedding.weight'].shape[0] == 322:
        hps.model.version = "v1"
    else:
        hps.model.version = "v2"
    version = hps.model.version
    # print("sovits版本:",hps.model.version)
    vq_model = SynthesizerTrn(
        hps.data.filter_length // 2 + 1,
        hps.train.segment_size // hps.data.hop_length,
        n_speakers=hps.data.n_speakers,
        **hps.model
    )
    if ("pretrained" not in sovits_path):
        del vq_model.enc_q
    if is_half == True:
        vq_model = vq_model.half().to(device)
    else:
        vq_model = vq_model.to(device)
    vq_model.eval()
    print(vq_model.load_state_dict(dict_s2["weight"], strict=False))
    dict_language = dict_language_v1 if version =='v1' else dict_language_v2
    with open("./weight.json")as f:
        data=f.read()
        data=json.loads(data)
        data["SoVITS"][version]=sovits_path
    with open("./weight.json","w")as f:f.write(json.dumps(data))
    if prompt_language is not None and text_language is not None:
        if prompt_language in list(dict_language.keys()):
            prompt_text_update, prompt_language_update = {'__type__':'update'},  {'__type__':'update', 'value':prompt_language}
        else:
            prompt_text_update = {'__type__':'update', 'value':''}
            prompt_language_update = {'__type__':'update', 'value':i18n("中文")}
        if text_language in list(dict_language.keys()):
            text_update, text_language_update = {'__type__':'update'}, {'__type__':'update', 'value':text_language}
        else:
            text_update = {'__type__':'update', 'value':''}
            text_language_update = {'__type__':'update', 'value':i18n("中文")}
        return  {'__type__':'update', 'choices':list(dict_language.keys())}, {'__type__':'update', 'choices':list(dict_language.keys())}, prompt_text_update, prompt_language_update, text_update, text_language_update
change_sovits_weights(sovits_path)


def change_gpt_weights(gpt_path):
    global hz, max_sec, t2s_model, config
    hz = 50
    dict_s1 = torch.load(gpt_path, map_location="cpu")
    config = dict_s1["config"]
    max_sec = config["data"]["max_sec"]
    t2s_model = Text2SemanticLightningModule(config, "****", is_train=False)
    t2s_model.load_state_dict(dict_s1["weight"])
    if is_half == True:
        t2s_model = t2s_model.half()
    t2s_model = t2s_model.to(device)
    t2s_model.eval()
    total = sum([param.nelement() for param in t2s_model.parameters()])
    print("Number of parameter: %.2fM" % (total / 1e6))
    with open("./weight.json")as f:
        data=f.read()
        data=json.loads(data)
        data["GPT"][version]=gpt_path
    with open("./weight.json","w")as f:f.write(json.dumps(data))
change_gpt_weights(gpt_path)


def get_spepc(hps, filename):
    audio = load_audio(filename, int(hps.data.sampling_rate))
    audio = torch.FloatTensor(audio)
    maxx=audio.abs().max()
    if(maxx>1):audio/=min(2,maxx)
    audio_norm = audio
    audio_norm = audio_norm.unsqueeze(0)
    spec = spectrogram_torch(
        audio_norm,
        hps.data.filter_length,
        hps.data.sampling_rate,
        hps.data.hop_length,
        hps.data.win_length,
        center=False,
    )
    return spec

def clean_text_inf(text, language, version):
    phones, word2ph, norm_text = clean_text(text, language, version)
    phones = cleaned_text_to_sequence(phones, version)
    return phones, word2ph, norm_text

dtype=torch.float16 if is_half == True else torch.float32
def get_bert_inf(phones, word2ph, norm_text, language):
    language=language.replace("all_","")
    if language == "zh":
        bert = get_bert_feature(norm_text, word2ph).to(device)#.to(dtype)
    else:
        bert = torch.zeros(
            (1024, len(phones)),
            dtype=torch.float16 if is_half == True else torch.float32,
        ).to(device)

    return bert

splits = {"，", "。", "？", "！", ",", ".", "?", "!", "~", ":", "：", "—", "…", }

def get_first(text):
    pattern = "[" + "".join(re.escape(sep) for sep in splits) + "]"
    text = re.split(pattern, text)[0].strip()
    return text

from text import chinese
def get_phones_and_bert(text,language,version,final=False):
    if language in {"en", "all_zh", "all_ja", "all_ko", "all_yue"}:
        language = language.replace("all_","")
        if language == "en":
            LangSegment.setfilters(["en"])
            formattext = " ".join(tmp["text"] for tmp in LangSegment.getTexts(text))
        else:
            # 因无法区别中日韩文汉字,以用户输入为准
            formattext = text
        while "  " in formattext:
            formattext = formattext.replace("  ", " ")
        if language == "zh":
            if re.search(r'[A-Za-z]', formattext):
                formattext = re.sub(r'[a-z]', lambda x: x.group(0).upper(), formattext)
                formattext = chinese.mix_text_normalize(formattext)
                return get_phones_and_bert(formattext,"zh",version)
            else:
                phones, word2ph, norm_text = clean_text_inf(formattext, language, version)
                bert = get_bert_feature(norm_text, word2ph).to(device)
        elif language == "yue" and re.search(r'[A-Za-z]', formattext):
                formattext = re.sub(r'[a-z]', lambda x: x.group(0).upper(), formattext)
                formattext = chinese.mix_text_normalize(formattext)
                return get_phones_and_bert(formattext,"yue",version)
        else:
            phones, word2ph, norm_text = clean_text_inf(formattext, language, version)
            bert = torch.zeros(
                (1024, len(phones)),
                dtype=torch.float16 if is_half == True else torch.float32,
            ).to(device)
    elif language in {"zh", "ja", "ko", "yue", "auto", "auto_yue"}:
        textlist=[]
        langlist=[]
        LangSegment.setfilters(["zh","ja","en","ko"])
        if language == "auto":
            for tmp in LangSegment.getTexts(text):
                langlist.append(tmp["lang"])
                textlist.append(tmp["text"])
        elif language == "auto_yue":
            for tmp in LangSegment.getTexts(text):
                if tmp["lang"] == "zh":
                    tmp["lang"] = "yue"
                langlist.append(tmp["lang"])
                textlist.append(tmp["text"])
        else:
            for tmp in LangSegment.getTexts(text):
                if tmp["lang"] == "en":
                    langlist.append(tmp["lang"])
                else:
                    # 因无法区别中日韩文汉字,以用户输入为准
                    langlist.append(language)
                textlist.append(tmp["text"])
        print(textlist)
        print(langlist)
        phones_list = []
        bert_list = []
        norm_text_list = []
        for i in range(len(textlist)):
            lang = langlist[i]
            phones, word2ph, norm_text = clean_text_inf(textlist[i], lang, version)
            bert = get_bert_inf(phones, word2ph, norm_text, lang)
            phones_list.append(phones)
            norm_text_list.append(norm_text)
            bert_list.append(bert)
        bert = torch.cat(bert_list, dim=1)
        phones = sum(phones_list, [])
        norm_text = ''.join(norm_text_list)

    if not final and len(phones) < 6:
        return get_phones_and_bert("." + text,language,version,final=True)

    return phones,bert.to(dtype),norm_text


def merge_short_text_in_array(texts, threshold):
    if (len(texts)) < 2:
        return texts
    result = []
    text = ""
    for ele in texts:
        text += ele
        if len(text) >= threshold:
            result.append(text)
            text = ""
    if (len(text) > 0):
        if len(result) == 0:
            result.append(text)
        else:
            result[len(result) - 1] += text
    return result
cache= {}
main_output = []
invalid_charts=['\\', '/', ':', '*', '?', '"', '<', '>', '|', '\n', '\r']
def get_tts_wav(ref_wav_path, prompt_text, prompt_language, text, text_language, how_to_cut=i18n("不切"),
                top_k=20, top_p=0.6, temperature=0.6, ref_free=False, speed=1, if_freeze=False, inp_refs=123,
                pause_duration=0.5):
    global cache,main_output,audio_name

    main_output=[]
    file_name = ''.join([char if char not in invalid_charts else '_' for char in text[:30].strip()])
    audio_name=file_name
    # file_name = text[:30]
    # file_name = file_name.strip()
    # for char in invalid_charts:
    #     file_name = file_name.replace(char, '_')
    if ref_wav_path:
        pass
    else:
        gr.Warning(i18n('请上传参考音频'))
    if text:
        pass
    else:
        gr.Warning(i18n('请填入推理文本'))
    t = []
    if prompt_text is None or len(prompt_text) == 0:
        ref_free = True
    t0 = ttime()
    prompt_language = dict_language[prompt_language]
    text_language = dict_language[text_language]

    if not ref_free:
        prompt_text = prompt_text.strip("\n")
        if (prompt_text[-1] not in splits): prompt_text += "。" if prompt_language != "en" else "."
        print(i18n("实际输入的参考文本:"), prompt_text)
    text = text.strip("\n")
    # if (text[0] not in splits and len(get_first(text)) < 4): text = "。" + text if text_language != "en" else "." + text

    print(i18n("实际输入的目标文本:"), text)
    zero_wav = np.zeros(
        int(hps.data.sampling_rate * 0.3),
        dtype=np.float16 if is_half == True else np.float32,
    )
    pause_samples = int(hps.data.sampling_rate * pause_duration)
    zero_wav1 = np.zeros(pause_samples, dtype=np.float16 if is_half else np.float32)
    if not ref_free:
        with torch.no_grad():
            wav16k, sr = librosa.load(ref_wav_path, sr=16000)
            if (wav16k.shape[0] > 160000 or wav16k.shape[0] < 48000):
                gr.Warning(i18n("参考音频在3~10秒范围外，请更换！"))
                raise OSError(i18n("参考音频在3~10秒范围外，请更换！"))
            wav16k = torch.from_numpy(wav16k)
            zero_wav_torch = torch.from_numpy(zero_wav)
            if is_half == True:
                wav16k = wav16k.half().to(device)
                zero_wav_torch = zero_wav_torch.half().to(device)
            else:
                wav16k = wav16k.to(device)
                zero_wav_torch = zero_wav_torch.to(device)
            wav16k = torch.cat([wav16k, zero_wav_torch])
            ssl_content = ssl_model.model(wav16k.unsqueeze(0))[
                "last_hidden_state"
            ].transpose(
                1, 2
            )  # .float()
            codes = vq_model.extract_latent(ssl_content)
            prompt_semantic = codes[0, 0]
            prompt = prompt_semantic.unsqueeze(0).to(device)

    t1 = ttime()
    t.append(t1 - t0)

    if (how_to_cut == i18n("凑四句一切")):
        text = cut1(text)
    elif (how_to_cut == i18n("凑50字一切")):
        text = cut2(text)
    elif (how_to_cut == i18n("按中文句号。切")):
        text = cut3(text)
    elif (how_to_cut == i18n("按英文句号.切")):
        text = cut4(text)
    elif (how_to_cut == i18n("按标点符号切")):
        text = cut5(text)
    while "\n\n" in text:
        text = text.replace("\n\n", "\n")
    print(i18n("实际输入的目标文本(切句后):"), text)
    texts = text.split("\n")
    texts = process_text(texts)
    texts = merge_short_text_in_array(texts, 1)
    audio_opt = []
    if not ref_free:
        phones1, bert1, norm_text1 = get_phones_and_bert(prompt_text, prompt_language, version)

    for i_text, text in enumerate(texts):
        # 解决输入目标文本的空行导致报错的问题
        if (len(text.strip()) == 0):
            continue
        if (text[-1] not in splits): text += "。" if text_language != "en" else "."
        print(i18n("实际输入的目标文本(每句):"), text)
        phones2, bert2, norm_text2 = get_phones_and_bert(text, text_language, version)
        print(i18n("前端处理后的文本(每句):"), norm_text2)
        if not ref_free:
            bert = torch.cat([bert1, bert2], 1)
            all_phoneme_ids = torch.LongTensor(phones1 + phones2).to(device).unsqueeze(0)
        else:
            bert = bert2
            all_phoneme_ids = torch.LongTensor(phones2).to(device).unsqueeze(0)

        bert = bert.to(device).unsqueeze(0)
        all_phoneme_len = torch.tensor([all_phoneme_ids.shape[-1]]).to(device)

        t2 = ttime()
        # cache_key="%s-%s-%s-%s-%s-%s-%s-%s"%(ref_wav_path,prompt_text,prompt_language,text,text_language,top_k,top_p,temperature)
        # print(cache.keys(),if_freeze)
        if (i_text in cache and if_freeze == True):
            pred_semantic = cache[i_text]
        else:
            with torch.no_grad():
                pred_semantic, idx = t2s_model.model.infer_panel(
                    all_phoneme_ids,
                    all_phoneme_len,
                    None if ref_free else prompt,
                    bert,
                    # prompt_phone_len=ph_offset,
                    top_k=top_k,
                    top_p=top_p,
                    temperature=temperature,
                    early_stop_num=hz * max_sec,
                )
                pred_semantic = pred_semantic[:, -idx:].unsqueeze(0)
                cache[i_text] = pred_semantic
        t3 = ttime()
        refers = []
        if (inp_refs):
            for path in inp_refs:
                try:
                    refer = get_spepc(hps, path.name).to(dtype).to(device)
                    refers.append(refer)
                except:
                    traceback.print_exc()
        if (len(refers) == 0): refers = [get_spepc(hps, ref_wav_path).to(dtype).to(device)]
        audio = (vq_model.decode(pred_semantic, torch.LongTensor(phones2).to(device).unsqueeze(0), refers,
                                 speed=speed).detach().cpu().numpy()[0, 0])
        max_audio = np.abs(audio).max()  # 简单防止16bit爆音
        if max_audio > 1: audio /= max_audio
        audio_opt.append(audio)
        # (by - katana，append新的zero_wave）
        audio_opt.append(zero_wav1)

        t4 = ttime()
        t.extend([t2 - t1, t3 - t2, t4 - t3])
        t1 = ttime()
    print("%.3f\t%.3f\t%.3f\t%.3f" %
          (t[0], sum(t[1::3]), sum(t[2::3]), sum(t[3::3]))
          )
    for item in audio_opt:
        main_output.append(item)
    concatenated_audio = np.concatenate(audio_opt, 0)
    file_path = os.path.join(output_dir, f"[主音频]_{file_name}.wav")
    write(file_path, hps.data.sampling_rate, (concatenated_audio * 32768).astype(np.int16))
    yield hps.data.sampling_rate, (np.concatenate(audio_opt, 0) * 32768).astype(
        np.int16
    )

def get_tts_wav2(line_index,is_edit, ref_wav_path, prompt_text, prompt_language, text, text_language, how_to_cut=i18n("不切"),
                top_k=20, top_p=0.6, temperature=0.6, ref_free=False, speed=1, if_freeze=False, inp_refs=123,
                pause_duration=0.5):
    global cache,main_output,audio_name
    if not is_edit:
        file_name = text[:30]
        file_name = file_name.strip()
        for char in invalid_charts:
            file_name = file_name.replace(char, '_')
    if len(main_output) > 0:
        pass
    else:
        gr.Warning(i18n("请先生成主音频，或取消勾选直接修改"))
        return
    if ref_wav_path:
        pass
    else:
        gr.Warning(i18n('请上传参考音频'))
    if text:
        pass
    else:
        gr.Warning(i18n('请填入推理文本'))
    t = []
    if prompt_text is None or len(prompt_text) == 0:
        ref_free = True
    t0 = ttime()
    prompt_language = dict_language[prompt_language]
    text_language = dict_language[text_language]

    if not ref_free:
        prompt_text = prompt_text.strip("\n")
        if (prompt_text[-1] not in splits): prompt_text += "。" if prompt_language != "en" else "."
        print(i18n("实际输入的参考文本:"), prompt_text)
    text = text.strip("\n")
    # if (text[0] not in splits and len(get_first(text)) < 4): text = "。" + text if text_language != "en" else "." + text

    print(i18n("实际输入的目标文本:"), text)
    zero_wav = np.zeros(
        int(hps.data.sampling_rate * 0.3),
        dtype=np.float16 if is_half == True else np.float32,
    )
    pause_samples = int(hps.data.sampling_rate * pause_duration)
    zero_wav1 = np.zeros(pause_samples, dtype=np.float16 if is_half else np.float32)
    if not ref_free:
        with torch.no_grad():
            wav16k, sr = librosa.load(ref_wav_path, sr=16000)
            if (wav16k.shape[0] > 160000 or wav16k.shape[0] < 48000):
                gr.Warning(i18n("参考音频在3~10秒范围外，请更换！"))
                raise OSError(i18n("参考音频在3~10秒范围外，请更换！"))
            wav16k = torch.from_numpy(wav16k)
            zero_wav_torch = torch.from_numpy(zero_wav)
            if is_half == True:
                wav16k = wav16k.half().to(device)
                zero_wav_torch = zero_wav_torch.half().to(device)
            else:
                wav16k = wav16k.to(device)
                zero_wav_torch = zero_wav_torch.to(device)
            wav16k = torch.cat([wav16k, zero_wav_torch])
            ssl_content = ssl_model.model(wav16k.unsqueeze(0))[
                "last_hidden_state"
            ].transpose(
                1, 2
            )  # .float()
            codes = vq_model.extract_latent(ssl_content)
            prompt_semantic = codes[0, 0]
            prompt = prompt_semantic.unsqueeze(0).to(device)

    t1 = ttime()
    t.append(t1 - t0)

    if (how_to_cut == i18n("凑四句一切")):
        text = cut1(text)
    elif (how_to_cut == i18n("凑50字一切")):
        text = cut2(text)
    elif (how_to_cut == i18n("按中文句号。切")):
        text = cut3(text)
    elif (how_to_cut == i18n("按英文句号.切")):
        text = cut4(text)
    elif (how_to_cut == i18n("按标点符号切")):
        text = cut5(text)
    while "\n\n" in text:
        text = text.replace("\n\n", "\n")
    print(i18n("实际输入的目标文本(切句后):"), text)
    texts = text.split("\n")
    texts = process_text(texts)
    texts = merge_short_text_in_array(texts, 1)
    audio_opt = []
    if not ref_free:
        phones1, bert1, norm_text1 = get_phones_and_bert(prompt_text, prompt_language, version)

    for i_text, text in enumerate(texts):
        # 解决输入目标文本的空行导致报错的问题
        if (len(text.strip()) == 0):
            continue
        if (text[-1] not in splits): text += "。" if text_language != "en" else "."
        print(i18n("实际输入的目标文本(每句):"), text)
        phones2, bert2, norm_text2 = get_phones_and_bert(text, text_language, version)
        print(i18n("前端处理后的文本(每句):"), norm_text2)
        if not ref_free:
            bert = torch.cat([bert1, bert2], 1)
            all_phoneme_ids = torch.LongTensor(phones1 + phones2).to(device).unsqueeze(0)
        else:
            bert = bert2
            all_phoneme_ids = torch.LongTensor(phones2).to(device).unsqueeze(0)

        bert = bert.to(device).unsqueeze(0)
        all_phoneme_len = torch.tensor([all_phoneme_ids.shape[-1]]).to(device)

        t2 = ttime()
        # cache_key="%s-%s-%s-%s-%s-%s-%s-%s"%(ref_wav_path,prompt_text,prompt_language,text,text_language,top_k,top_p,temperature)
        # print(cache.keys(),if_freeze)
        if (i_text in cache and if_freeze == True):
            pred_semantic = cache[i_text]
        else:
            with torch.no_grad():
                pred_semantic, idx = t2s_model.model.infer_panel(
                    all_phoneme_ids,
                    all_phoneme_len,
                    None if ref_free else prompt,
                    bert,
                    # prompt_phone_len=ph_offset,
                    top_k=top_k,
                    top_p=top_p,
                    temperature=temperature,
                    early_stop_num=hz * max_sec,
                )
                pred_semantic = pred_semantic[:, -idx:].unsqueeze(0)
                cache[i_text] = pred_semantic
        t3 = ttime()
        refers = []
        if (inp_refs):
            for path in inp_refs:
                try:
                    refer = get_spepc(hps, path.name).to(dtype).to(device)
                    refers.append(refer)
                except:
                    traceback.print_exc()
        if (len(refers) == 0): refers = [get_spepc(hps, ref_wav_path).to(dtype).to(device)]
        audio = (vq_model.decode(pred_semantic, torch.LongTensor(phones2).to(device).unsqueeze(0), refers,
                                 speed=speed).detach().cpu().numpy()[0, 0])
        max_audio = np.abs(audio).max()  # 简单防止16bit爆音
        if max_audio > 1: audio /= max_audio
        audio_opt.append(audio)
        # (by - katana，append新的zero_wave）
        audio_opt.append(zero_wav1)
        t4 = ttime()
        t.extend([t2 - t1, t3 - t2, t4 - t3])
        t1 = ttime()
    print("%.3f\t%.3f\t%.3f\t%.3f" %
          (t[0], sum(t[1::3]), sum(t[2::3]), sum(t[3::3]))
          )
    if not is_edit:
        concatenated_audio = np.concatenate(audio_opt, 0)
        file_path = os.path.join(output_dir, f"{file_name}.wav")
        write(file_path, hps.data.sampling_rate, (concatenated_audio * 32768).astype(np.int16))
    else:
        new_auido = np.concatenate(audio_opt[:-1], 0)
        new_index = 2 * (line_index - 1)
        main_output[new_index] = new_auido
        concatenated_audio = np.concatenate(main_output, 0)
        file_path = os.path.join(output_dir, f"[修改后主音频]_{audio_name}.wav")
        write(file_path, hps.data.sampling_rate, (concatenated_audio * 32768).astype(np.int16))

    return hps.data.sampling_rate, (np.concatenate(audio_opt, 0) * 32768).astype(
        np.int16
    )



def split(todo_text):
    todo_text = todo_text.replace("……", "。").replace("——", "，")
    if todo_text[-1] not in splits:
        todo_text += "。"
    i_split_head = i_split_tail = 0
    len_text = len(todo_text)
    todo_texts = []
    while 1:
        if i_split_head >= len_text:
            break  # 结尾一定有标点，所以直接跳出即可，最后一段在上次已加入
        if todo_text[i_split_head] in splits:
            i_split_head += 1
            todo_texts.append(todo_text[i_split_tail:i_split_head])
            i_split_tail = i_split_head
        else:
            i_split_head += 1
    return todo_texts


def cut1(inp):
    inp = inp.strip("\n")
    inps = split(inp)
    split_idx = list(range(0, len(inps), 4))
    split_idx[-1] = None
    if len(split_idx) > 1:
        opts = []
        for idx in range(len(split_idx) - 1):
            opts.append("".join(inps[split_idx[idx]: split_idx[idx + 1]]))
    else:
        opts = [inp]
    opts = [item for item in opts if not set(item).issubset(punctuation)]
    return "\n".join(opts)


def cut2(inp):
    inp = inp.strip("\n")
    inps = split(inp)
    if len(inps) < 2:
        return inp
    opts = []
    summ = 0
    tmp_str = ""
    for i in range(len(inps)):
        summ += len(inps[i])
        tmp_str += inps[i]
        if summ > 50:
            summ = 0
            opts.append(tmp_str)
            tmp_str = ""
    if tmp_str != "":
        opts.append(tmp_str)
    # print(opts)
    if len(opts) > 1 and len(opts[-1]) < 50:  ##如果最后一个太短了，和前一个合一起
        opts[-2] = opts[-2] + opts[-1]
        opts = opts[:-1]
    opts = [item for item in opts if not set(item).issubset(punctuation)]
    return "\n".join(opts)


def cut3(inp):
    inp = inp.strip("\n")
    opts = ["%s" % item for item in inp.strip("。").split("。")]
    opts = [item for item in opts if not set(item).issubset(punctuation)]
    return  "\n".join(opts)

def cut4(inp):
    inp = inp.strip("\n")
    opts = ["%s" % item for item in inp.strip(".").split(".")]
    opts = [item for item in opts if not set(item).issubset(punctuation)]
    return "\n".join(opts)


# contributed by https://github.com/AI-Hobbyist/GPT-SoVITS/blob/main/GPT_SoVITS/inference_webui.py
def cut5(inp):
    inp = inp.strip("\n")
    punds = {',', '.', ';', '?', '!', '、', '，', '。', '？', '！', ';', '：', '…'}
    mergeitems = []
    items = []

    for i, char in enumerate(inp):
        if char in punds:
            if char == '.' and i > 0 and i < len(inp) - 1 and inp[i - 1].isdigit() and inp[i + 1].isdigit():
                items.append(char)
            else:
                items.append(char)
                mergeitems.append("".join(items))
                items = []
        else:
            items.append(char)

    if items:
        mergeitems.append("".join(items))

    opt = [item for item in mergeitems if not set(item).issubset(punds)]
    return "\n".join(opt)

def process_text(texts):
    _text=[]
    if all(text in [None, " ", "\n",""] for text in texts):
        raise ValueError(i18n("请输入有效文本"))
    for text in texts:
        if text in  [None, " ", ""]:
            pass
        else:
            _text.append(text)
    return _text



def html_center(text, label='p'):
    return f"""<div style="text-align: center; margin: 100; padding: 50;">
                <{label} style="margin: 0; padding: 0;">{text}</{label}>
                </div>"""

def html_left(text, label='p'):
    return f"""<div style="text-align: left; margin: 0; padding: 0;">
                <{label} style="margin: 0; padding: 0;">{text}</{label}>
                </div>"""

# (by - katana增加参考音频列表）
reference_wavs=["选择参考音频或自己上传"]
for name in os.listdir("./refwavs"):
    reference_wavs.append(name)
#不一定有用 更新下拉列表
def change_ref_choices():
    reference_wavs = [i18n("Please select the reference audio or upload it yourself.")]
    for name in os.listdir("./refwavs/"):
        reference_wavs.append(name)
    return {"choices":reference_wavs, "__type__": "update"}


# (by - katana 参考音频列表移除[]）
def replace_speaker(text):
    return re.sub(r"\[.*?\]", "", text, flags=re.UNICODE)

def change_wav(audio_path):
    text = audio_path.replace(".wav","").replace(".mp3","").replace(".WAV","")
    text = replace_speaker(text)
    return f"./refwavs/{audio_path}",text

#(by - katana 切分文本发送到下面文字框中)
def split_text_and_fill_boxes(input_text, *textboxes):
    sentences = []
    # 按句号切分文本
    for line in input_text.split('\n'):
        sentences.extend(line.split('。'))
    # 去除空字符串
    sentences = [sentence.strip()+'。' for sentence in sentences if sentence.strip()]

    # 更新每个文本框的内容
    # updates = []
    # for i, textbox in enumerate(textboxes):
    #     if i < len(sentences):
    #         updates.append(gr.update(value=sentences[i]))
    #     else:
    #         updates.append(gr.update(value=""))
    return sentences
# (by - katana 按照段落切分)
def split_by_n(input_text, *textboxes):
    # 去掉全角括号及括号里的内容
    cleaned_text = re.sub(r"\(.*?\)", "", input_text)
    # 按换行符切分文本
    sentences = [line.strip() for line in cleaned_text.split('\n') if line.strip()]

    # # 更新每个文本框的内容
    # updates = []
    # for i, textbox in enumerate(textboxes):
    #     if i < len(sentences):
    #         updates.append(gr.update(value=sentences[i]))
    #     else:
    #         updates.append(gr.update(value=""))
    return sentences
# (by - katana 热词替换 需要同级目录有一个hotword.json文件)
def hot_replace(input_text):
    with open('./GPT_SoVITS/hotwords.json', 'r', encoding='utf-8') as file:
        hotwords_dict = json.load(file)
    for key, value in hotwords_dict.items():
        input_text = input_text.replace(key, value)
    return gr.update(value=input_text)

def open_folder_callback():
    folder_path = "生成记录"  # 你可以替换为实际的文件夹路径
    subprocess.run(['explorer', folder_path])

with gr.Blocks(title="GPT-SoVITS WebUI") as app:
    gr.Markdown(
        value=i18n("本软件以MIT协议开源, 作者不对软件具备任何控制力, 使用软件者、传播软件导出的声音者自负全责. <br>如不认可该条款, 则不能使用或引用软件包内任何代码和文件. 详见根目录<b>LICENSE</b>.")
    )
    with gr.Tabs():
        with gr.TabItem(i18n("语音生成")):  # 提前随机切片防止uvr5爆内存->uvr5->slicer->asr->打标
            open_folder = gr.Button(i18n("打开生成文件夹"), variant="primary", size='lg')
            open_folder.click(open_folder_callback)
            with gr.Group():
                gr.Markdown(html_center(i18n("模型切换"),'h3'))
                with gr.Row():
                    GPT_dropdown = gr.Dropdown(label=i18n("GPT模型列表"), choices=sorted(GPT_names, key=custom_sort_key), value=gpt_path, interactive=True, scale=14)
                    SoVITS_dropdown = gr.Dropdown(label=i18n("SoVITS模型列表"), choices=sorted(SoVITS_names, key=custom_sort_key), value=sovits_path, interactive=True, scale=14)
                    refresh_button = gr.Button(i18n("刷新模型路径"), variant="primary", scale=12)
                    refresh_button.click(fn=change_choices, inputs=[], outputs=[SoVITS_dropdown, GPT_dropdown])

                gr.Markdown(html_center(i18n("*请上传并填写参考信息"),'h3'))
                with gr.Row():
                    with gr.Column(scale=16):
                        inp_ref = gr.Audio(label=i18n("请上传3~10秒内参考音频，超过会报错！"), type="filepath", scale=13)
                        with gr.Row():
                        #(by - katana 参考音频列表）
                            wavs_dropdown = gr.Dropdown(label="参考音频列表",choices=reference_wavs,value="选择参考音频或者自己上传",interactive=True,scale=5)
                            refresh_ref_button=gr.Button("刷新",scale=1)
                            refresh_ref_button.click(fn=change_ref_choices,inputs=[],outputs=wavs_dropdown)
                    with gr.Column(scale=13):
                        ref_text_free = gr.Checkbox(label=i18n("开启无参考文本模式。不填参考文本亦相当于开启。"), value=False, interactive=True, show_label=True,scale=1)
                        # gr.Markdown(html_center(i18n("使用无参考文本模式时建议使用微调的GPT，听不清参考音频说的啥(不晓得写啥)可以开。<br>开启后无视填写的参考文本。")))
                        prompt_text = gr.Textbox(label=i18n("参考音频的文本"), value="", lines=5, max_lines=5,scale=1)

                    wavs_dropdown.change(change_wav,[wavs_dropdown],[inp_ref,prompt_text])
                    with gr.Column(scale=14):
                        prompt_language = gr.Dropdown(
                            label=i18n("参考音频的语种"), choices=list(dict_language.keys()), value=i18n("中文"),
                        )
                        inp_refs = gr.File(label=i18n("辅助参考音频"),file_count="multiple")
                gr.Markdown(html_center(i18n("*请填写需要合成的目标文本和语种模式"),'h3'))
                with gr.Row():
                    with gr.Column(scale=13):
                        text = gr.Textbox(label=i18n("需要合成的文本"), value="", lines=26, max_lines=26)
                    with gr.Column(scale=7):
                        text_language = gr.Dropdown(
                                label=i18n("需要合成的语种")+i18n(".限制范围越小判别效果越好。"), choices=list(dict_language.keys()), value=i18n("中文"), scale=1
                            )
                        how_to_cut = gr.Dropdown(
                                label=i18n("怎么切"),
                                choices=[i18n("不切"), i18n("凑四句一切"), i18n("凑50字一切"), i18n("按中文句号。切"), i18n("按英文句号.切"), i18n("按标点符号切"), ],
                                value=i18n("按中文句号。切"),
                                interactive=True, scale=1
                            )
                        gr.Markdown(value=html_center(i18n("语速调整，高为更快")))
                        if_freeze=gr.Checkbox(label=i18n("是否直接对上次合成结果调整语速和音色。防止随机性。"), value=False, interactive=True,show_label=True, scale=1)
                        speed = gr.Slider(minimum=0.6,maximum=1.65,step=0.05,label=i18n("语速"),value=1,interactive=True, scale=1)
                        pause_duration = gr.Slider(
                            minimum=0.01,
                            maximum=2,
                            step=0.01,
                            label=i18n("音频片段间隔时长(秒)"),
                            value=0.2,
                            interactive=True,
                            scale=1
                        )
                        gr.Markdown(html_center(i18n("GPT采样参数(无参考文本时不要太低。不懂就用默认)：")))
                        top_k = gr.Slider(minimum=1,maximum=100,step=1,label=i18n("top_k（采样率，越高语气越丰富）"),value=15,interactive=True, scale=1)
                        top_p = gr.Slider(minimum=0,maximum=1,step=0.05,label=i18n("top_p（建议不动）"),value=1,interactive=True, scale=1)
                        temperature = gr.Slider(minimum=0,maximum=1,step=0.05,label=i18n("temperature(越低越稳定，但是语气稍有平淡)"),value=1,interactive=True,  scale=1)
                        # (by - katana 热词替换按钮）
                        replace_hot_words = gr.Button("替换热词")
                        replace_hot_words.click(fn=hot_replace, inputs=text, outputs=text)
                    # with gr.Column():
                    #     gr.Markdown(value=i18n("手工调整音素。当音素框不为空时使用手工音素输入推理，无视目标文本框。"))
                    #     phoneme=gr.Textbox(label=i18n("音素框"), value="")
                    #     get_phoneme_button = gr.Button(i18n("目标文本转音素"), variant="primary")
                with gr.Row():
                    inference_button = gr.Button(i18n("合成语音"), variant="primary", size='lg', scale=25)
                    output = gr.Audio(label=i18n("输出的语音"), scale=14)

                inference_button.click(
                    get_tts_wav,
                    [inp_ref, prompt_text, prompt_language, text, text_language, how_to_cut, top_k, top_p, temperature, ref_text_free,speed,if_freeze,inp_refs,pause_duration],
                    [output],
                )
                SoVITS_dropdown.change(change_sovits_weights, [SoVITS_dropdown,prompt_language,text_language], [prompt_language,text_language,prompt_text,prompt_language,text,text_language])
                GPT_dropdown.change(change_gpt_weights, [GPT_dropdown], [])

                # (by - katana 校对标签页)
        with gr.Column():  # 提前随机切片防止uvr5爆内存->uvr5->slicer->asr->打标
            lines=gr.State([])
            split_button = gr.Button(value="切分文本（文本按句号切分，方便单独生成）", variant="primary", size='lg')
            # (by - katana 按段落切分按钮)
            split_button2 = gr.Button(value="按段落切分", variant="primary", size='lg')
            is_edit = gr.Checkbox(label='是否对音频直接修改(如果是，会对整段音频单句替换，不会在“生成记录”文件夹生成单句语音)', value=False)
            split_button.click(fn=split_text_and_fill_boxes,inputs=[text],outputs=lines)
            split_button2.click(fn=split_by_n, inputs=[text], outputs=lines)


            @gr.render(inputs=lines)
            def show_renders(lines):
                index=0
                for i in lines:
                    index +=1
                    with gr.Row():
                        line_index = gr.State(index)
                        text_line = gr.Textbox(i,label=f'切分文本{index}',scale=4)
                        button = gr.Button('重新生成',scale=1)
                        audio_opt = gr.Audio(scale=2)
                    button.click(fn=get_tts_wav2, inputs=[line_index,is_edit,inp_ref, prompt_text, prompt_language, text_line, text_language, how_to_cut, top_k, top_p, temperature, ref_text_free,speed,if_freeze,inp_refs,pause_duration], outputs=audio_opt)

            # with gr.Accordion("重新生成列表"):
            #     textboxes = []
            #     for i in range(100):  # 创建200个水平布局
            #         with gr.Row():  # 每行都是一个新的水平布局
            #             text_input = gr.Textbox(label=f"切分文本 {i + 1}", scale=4)
            #             button = gr.Button(value="重新生成", scale=1)
            #             audio_output = gr.Audio(scale=2)
            #             # 将按钮与函数绑定，传递文本框的内容作为输入
            #             button.click(fn=get_tts_wav, inputs=[gr.State("regenerate"),inp_ref, prompt_text, prompt_language, text_input, text_language, how_to_cut, top_k, top_p, temperature, ref_text_free,speed,if_freeze,inp_refs,pause_duration], outputs=audio_output)
            #             textboxes.append(text_input)
            # split_button.click(fn=split_text_and_fill_boxes, inputs=[text, *textboxes], outputs=textboxes)
            # split_button2.click(fn=split_by_n, inputs=[text, *textboxes], outputs=textboxes)
        # gr.Markdown(value=i18n("文本切分工具。太长的文本合成出来效果不一定好，所以太长建议先切。合成会根据文本的换行分开合成再拼起来。"))
        # with gr.Row():
        #     text_inp = gr.Textbox(label=i18n("需要合成的切分前文本"), value="")
        #     button1 = gr.Button(i18n("凑四句一切"), variant="primary")
        #     button2 = gr.Button(i18n("凑50字一切"), variant="primary")
        #     button3 = gr.Button(i18n("按中文句号。切"), variant="primary")
        #     button4 = gr.Button(i18n("按英文句号.切"), variant="primary")
        #     button5 = gr.Button(i18n("按标点符号切"), variant="primary")
        #     text_opt = gr.Textbox(label=i18n("切分后文本"), value="")
        #     button1.click(cut1, [text_inp], [text_opt])
        #     button2.click(cut2, [text_inp], [text_opt])
        #     button3.click(cut3, [text_inp], [text_opt])
        #     button4.click(cut4, [text_inp], [text_opt])
        #     button5.click(cut5, [text_inp], [text_opt])
        # gr.Markdown(html_center(i18n("后续将支持转音素、手工修改音素、语音合成分步执行。")))

if __name__ == '__main__':
    app.queue().launch(#concurrency_count=511, max_size=1022
        server_name="0.0.0.0",
        inbrowser=True,
        share=is_share,
        server_port=infer_ttswebui,
        quiet=True,
    )



