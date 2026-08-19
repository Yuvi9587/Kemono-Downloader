import os
import csv
import threading
import warnings
import re
import numpy as np
from PIL import Image
from PySide6.QtCore import QSettings

warnings.filterwarnings("ignore", category=UserWarning, module="onnxruntime")

class VisualSorter:
    _instance = None
    _lock = threading.Lock()
    
    @classmethod
    def get_instance(cls, model_path, csv_path):
        if cls._instance is None:
            with cls._lock: 
                if cls._instance is None:
                    cls._instance = cls(model_path, csv_path)
        return cls._instance

    def __init__(self, model_path, csv_path):
        import onnxruntime as ort 
        
        settings = QSettings("MediaDownloader", "VisualSort")
        hw_choice = settings.value("execution_provider", "cpu", type=str)
        
        providers = ["CPUExecutionProvider"]
        if hw_choice == "cuda":
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        elif hw_choice == "dml":
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
            
        try:
            self.model = ort.InferenceSession(model_path, providers=providers)
            active_providers = self.model.get_providers()
            print("\n" + "="*40)
            print("[AI] VISUAL SORT ENGINE INITIALIZED")
            print("="*40)
            if "CUDAExecutionProvider" in active_providers:
                print("[OK] Hardware Status : NVIDIA GPU (CUDA) Active!")
            elif "DmlExecutionProvider" in active_providers:
                print("[OK] Hardware Status : AMD/Intel GPU (DirectML) Active!")
            else:
                print("[!!] Hardware Status : CPU Mode Active (Standard/Fallback)")
            print(f"[  ] Loaded Providers : {active_providers}")
            print("="*40 + "\n")
        except Exception as e:
            print(f"\n[X] Hardware Error: Failed to load '{hw_choice}'. Reason: {e}")
            print("[!] Falling back to safe CPU mode...\n")
            self.model = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        
        self.tags = []
        self.character_start_idx = None
        self.character_end_idx = None
        
        with open(csv_path, encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)
            for row in reader:
                tag_name = row[1].replace("_", " ").lower()
                category = row[2]
                if category == "4" and self.character_start_idx is None:
                    self.character_start_idx = reader.line_num - 2
                elif category != "4" and self.character_start_idx is not None and self.character_end_idx is None:
                    self.character_end_idx = reader.line_num - 2
                self.tags.append(tag_name)
                
        if self.character_start_idx is None:
            self.character_start_idx = len(self.tags)
        if self.character_end_idx is None:
            self.character_end_idx = len(self.tags)

        self.fallback_rules = []
        fallback_path = os.path.join(os.path.dirname(model_path), "fallback.csv")
        if os.path.exists(fallback_path):
            with open(fallback_path, encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader, None) 
                for row in reader:
                    if not row or len(row) < 3: 
                        continue
                        
                    char_name = row[0].strip().replace("_", " ").title()
                    raw_tags = row[2]
                    
                    rule_tags = []
                    negative_tags = []
                    mandatory_tags = [] 
                    
                    for t in raw_tags.split('|'):
                        t = t.strip().lower()
                        if not t: continue
                        
                        if t.startswith('!') or t.startswith('-'):
                            negative_tags.append(t[1:].strip().replace("_", " "))
                        elif t.startswith('*') or t.startswith('+'):
                            clean_t = t[1:].strip().replace("_", " ")
                            mandatory_tags.append(clean_t)
                            rule_tags.append(clean_t) 
                        else:
                            rule_tags.append(t.replace("_", " "))
                    
                    if rule_tags:
                        self.fallback_rules.append((char_name, rule_tags, negative_tags, mandatory_tags))

    def get_current_threshold(self):
        settings = QSettings("MediaDownloader", "VisualSort")
        return settings.value("char_threshold", 50, type=int) / 100.0

    def get_fallback_threshold(self):
        settings = QSettings("MediaDownloader", "VisualSort")
        return settings.value("fallback_threshold", 30, type=int) / 100.0

    def get_fallback_match_count(self):
        settings = QSettings("MediaDownloader", "VisualSort")
        return settings.value("fallback_tag_matches", 3, type=int)

    def is_skin_tag(self, tag):
        words = tag.replace("-", " ").split()
        return "skin" in words or "skinned" in words or "tan" in words

    def is_identity_tag(self, tag):
        words = tag.split()
        colors = ["red", "blue", "green", "yellow", "purple", "pink", "black", "white", 
                  "brown", "blonde", "silver", "grey", "gray", "orange", "dark", "pale", 
                  "tan", "multi-colored", "two-tone", "gradient"]
        for color in colors:
            if f"{color} hair" in tag or f"{color} eyes" in tag or f"{color} skin" in tag:
                return True
                
        permanent_markers = {"scar", "tattoo", "freckles", "mole", "heterochromia", "birthmark"}
        if any(marker in words for marker in permanent_markers):
            return True
            
        hair_types = ["spiked hair", "curly hair", "wavy hair", "straight hair", "messy hair", 
                      "drill hair", "twin drills", "afro", "dreadlocks", "ahoge", "twintails", 
                      "ponytail", "braid", "twin braids"]
        if tag in hair_types:
            return True
        return False

    def process_image(self, image_path, candidate_chars=None):
        try:
            def evaluate_single_frame(image_frame):
                input_layer = self.model.get_inputs()[0]
                target_size = input_layer.shape[1]
                ratio = float(target_size) / max(image_frame.size)
                new_size = tuple([int(x * ratio) for x in image_frame.size])
                image_resized = image_frame.resize(new_size, Image.LANCZOS)
                square = Image.new("RGB", (target_size, target_size), (255, 255, 255))
                square.paste(image_resized, ((target_size - new_size[0]) // 2, (target_size - new_size[1]) // 2))
                
                image_array = np.array(square).astype(np.float32)[:, :, ::-1]
                image_array = np.expand_dims(image_array, axis=0)
                
                preds = self.model.run(None, {input_layer.name: image_array})[0][0]
                
                char_preds = preds[self.character_start_idx:self.character_end_idx]
                char_tags = self.tags[self.character_start_idx:self.character_end_idx]
                
                general_preds = preds[:self.character_start_idx]
                general_tags = self.tags[:self.character_start_idx]
                
                current_threshold = self.get_current_threshold()
                top_general_indices = np.argsort(general_preds)[::-1][:5]
                top_tags_list = [(general_tags[i], float(general_preds[i])) for i in top_general_indices]

                result = {"best_char": None, "top_3_chars": [], "threshold": current_threshold, "reason": "", "top_tags": top_tags_list}

                max_char_score = 0
                if len(char_tags) > 0:
                    global_top_indices = np.argsort(char_preds)[::-1][:3]
                    global_top_chars = [(char_tags[i].title(), float(char_preds[i])) for i in global_top_indices]
                    
                    if candidate_chars:
                        normalized_cands = [c.lower().replace('_', ' ').strip() for c in candidate_chars]
                        valid_indices = []
                        
                        for i, t in enumerate(char_tags):
                            raw_onnx_tag = t.lower().replace('_', ' ') 
                            for cand in normalized_cands:
                                pattern = r'(?:^|[\s\-(])' + re.escape(cand) + r'(?:[\s\-)]|$)'
                                if re.search(pattern, raw_onnx_tag):
                                    valid_indices.append(i)
                                    break 
                                    
                        if valid_indices:
                            candidate_top_indices = sorted(valid_indices, key=lambda i: char_preds[i], reverse=True)[:3]
                            cand_score = float(char_preds[candidate_top_indices[0]])
                            
                            if cand_score > current_threshold:
                                result["top_3_chars"] = [(char_tags[i].title(), float(char_preds[i])) for i in candidate_top_indices]
                                result["best_char"] = result["top_3_chars"][0][0]
                                result["reason"] = "success (matched candidate from title)"
                                return result

                    global_max_score = global_top_chars[0][1] if global_top_chars else 0
                    if global_max_score > current_threshold:
                        result["top_3_chars"] = global_top_chars
                        result["best_char"] = global_top_chars[0][0]
                        result["reason"] = "success (AI found hidden character not in title)"
                        return result
                        
                    result["top_3_chars"] = global_top_chars
                    max_char_score = global_max_score

                fallback_threshold = self.get_fallback_threshold()
                user_required_matches = self.get_fallback_match_count()
                
                general_tag_scores = {general_tags[i]: float(general_preds[i]) for i in range(len(general_tags))}
                
                colors = ["red", "blue", "green", "yellow", "purple", "pink", "black", "white", 
                          "brown", "blonde", "silver", "grey", "gray", "orange", "dark", "pale", "tan"]
                hair_lengths = ["short hair", "medium hair", "long hair", "very long hair", "absurdly long hair", "bald"]
                exotic_skin_colors = ["red skin", "blue skin", "green skin", "purple skin", "grey skin", "dark skin", "tan", "dark-skinned female", "dark-skinned male"]
                mutation_traits = ["horns", "tail", "wings", "halo", "animal ears", "cat ears", "fox ears", "dog ears", "pointed ears", "elf ears"]
                          
                highest_hair = ("", 0.0)
                highest_eyes = ("", 0.0)
                highest_length = ("", 0.0)
                highest_exotic_skin = ("", 0.0)
                highest_mutation = ("", 0.0)
                
                has_mixed_hair = any(general_tag_scores.get(t, 0.0) > 0.25 for t in ["multi-colored hair", "two-tone hair", "gradient hair", "streaked hair"])
                has_mixed_eyes = general_tag_scores.get("heterochromia", 0.0) > 0.25
                has_multiple_people = any(general_tag_scores.get(t, 0.0) > 0.30 for t in ["2girls", "3girls", "4girls", "multiple girls", "2boys", "3boys", "multiple boys"])
                
                for t, s in general_tag_scores.items():
                    if s > 0.15: 
                        for c in colors:
                            if f"{c} hair" in t and s > highest_hair[1]: highest_hair = (t, s)
                            if f"{c} eyes" in t and s > highest_eyes[1]: highest_eyes = (t, s)
                        if t in hair_lengths and s > highest_length[1]: highest_length = (t, s)
                        
                        if t in exotic_skin_colors and s > highest_exotic_skin[1]: highest_exotic_skin = (t, s)
                        if t in mutation_traits and s > highest_mutation[1]: highest_mutation = (t, s)

                rule_sets = []
                if candidate_chars:
                    normalized_candidates = [c.lower().replace('_', ' ').strip() for c in candidate_chars]
                    cand_rules = [r for r in self.fallback_rules if r[0].lower().replace('_', ' ').strip() in normalized_candidates]
                    other_rules = [r for r in self.fallback_rules if r not in cand_rules]
                    
                    if cand_rules: rule_sets.append(("Title Candidate Pass", cand_rules))
                    if other_rules: rule_sets.append(("Hidden Character Pass", other_rules))
                else:
                    rule_sets.append(("Global Pass", self.fallback_rules))

                global_best_rejected_reason = ""
                highest_rejected_score_overall = 0

                for pass_name, current_rules in rule_sets:
                    best_fallback_char = None
                    best_match_score = 0.0
                    best_match_count = 0
                    best_fallback_tag_details = ""
                    best_identity_tags = []
                    
                    pass_best_rejected_reason = ""
                    highest_rejected_score = 0

                    for char_name, rule_tags, negative_tags, mandatory_tags in current_rules:
                        rule_skin_tags = [t for t in rule_tags if self.is_skin_tag(t)]
                        missing_mandatory_skin = False
                        missing_skin_tag_name = ""
                        
                        for s_tag in rule_skin_tags:
                            if general_tag_scores.get(s_tag, 0.0) < fallback_threshold:
                                missing_mandatory_skin = True
                                missing_skin_tag_name = s_tag
                                break
                                
                        matched_tags = []
                        rule_identity_tags = []
                        match_confidence_sum = 0.0
                        rule_has_conflict = False
                        conflict_reasons = []
                        
                        for tag in rule_tags:
                            score = general_tag_scores.get(tag, 0.0)
                            is_hair_tag = any(f"{c} hair" in tag for c in colors)
                            is_eye_tag = any(f"{c} eyes" in tag for c in colors)
                            is_length_tag = tag in hair_lengths
                            
                            if is_hair_tag and highest_hair[0] and not has_mixed_hair:
                                if tag not in highest_hair[0] and highest_hair[0] not in tag:
                                    if highest_hair[1] >= 0.50 and score < (highest_hair[1] - 0.30): 
                                        rule_has_conflict = True
                                        conflict_reasons.append(f"Image has {highest_hair[0]} vs Rule wants {tag}")
                            if is_eye_tag and highest_eyes[0] and not has_mixed_eyes:
                                if tag not in highest_eyes[0] and highest_eyes[0] not in tag:
                                    if highest_eyes[1] >= 0.60 and score < (highest_eyes[1] - 0.30):
                                        rule_has_conflict = True
                                        conflict_reasons.append(f"Image has {highest_eyes[0]} vs Rule wants {tag}")
                            if is_length_tag and highest_length[0]:
                                if tag != highest_length[0]:
                                    if highest_length[1] >= 0.50 and score < (highest_length[1] - 0.30): 
                                        rule_has_conflict = True
                                        conflict_reasons.append(f"Image has {highest_length[0]} vs Rule wants {tag}")

                            if score >= fallback_threshold:
                                matched_tags.append(f"{tag}: {score:.2f}")
                                match_confidence_sum += score 
                                if self.is_identity_tag(tag): rule_identity_tags.append(tag)
                        
                        if highest_exotic_skin[0] and highest_exotic_skin[1] >= 0.60 and not has_multiple_people:
                            rule_has_skin_tag = any(self.is_skin_tag(t) for t in rule_tags)
                            if not rule_has_skin_tag:
                                rule_has_conflict = True
                                conflict_reasons.append(f"Image has {highest_exotic_skin[0]} vs Rule assumes default light skin")
                            elif highest_exotic_skin[0] not in rule_tags:
                                rule_has_conflict = True
                                conflict_reasons.append(f"Image has {highest_exotic_skin[0]} vs Rule wants different skin")

                        if highest_mutation[0] and highest_mutation[1] >= 0.60 and not has_multiple_people:
                            mutation_base = highest_mutation[0].split()[-1] 
                            if not any(mutation_base in t for t in rule_tags):
                                rule_has_conflict = True
                                conflict_reasons.append(f"Image has {highest_mutation[0]} vs Rule assumes normal human")

                        current_match_count = len(matched_tags)
                        required_matches = min(user_required_matches, len(rule_tags))

                        rule_failed_negative = False
                        violating_neg_tag = ""
                        for n_tag in negative_tags:
                            if general_tag_scores.get(n_tag, 0.0) >= fallback_threshold:
                                rule_failed_negative = True
                                violating_neg_tag = n_tag
                                break

                        rule_failed_mandatory = False
                        missing_man_tag = ""
                        for m_tag in mandatory_tags:
                            if general_tag_scores.get(m_tag, 0.0) < fallback_threshold:
                                rule_failed_mandatory = True
                                missing_man_tag = m_tag
                                break

                        if missing_mandatory_skin:
                            if current_match_count >= highest_rejected_score:
                                highest_rejected_score = current_match_count
                                pass_best_rejected_reason = f"Almost matched {char_name}, but missing mandatory skin tag: {missing_skin_tag_name}"
                            continue
                            
                        if rule_has_conflict:
                            if current_match_count >= highest_rejected_score:
                                highest_rejected_score = current_match_count
                                pass_best_rejected_reason = f"Almost matched {char_name}, but blocked by conflict ({' & '.join(conflict_reasons)})"
                            continue
                            
                        if rule_failed_negative:
                            if current_match_count >= highest_rejected_score:
                                highest_rejected_score = current_match_count
                                pass_best_rejected_reason = f"Almost matched {char_name}, but blocked by Negative Tag (!{violating_neg_tag})"
                            continue

                        if rule_failed_mandatory:
                            if current_match_count >= highest_rejected_score:
                                highest_rejected_score = current_match_count
                                pass_best_rejected_reason = f"Almost matched {char_name}, but missing Mandatory Tag (*{missing_man_tag})"
                            continue

                        if len(matched_tags) >= required_matches:
                            if len(rule_identity_tags) == 0:
                                if current_match_count >= highest_rejected_score:
                                    highest_rejected_score = current_match_count
                                    pass_best_rejected_reason = f"Almost matched {char_name}, but missing required Identity Tag"
                                continue
                            
                            rule_score = match_confidence_sum / len(rule_tags)
                            
                            if rule_score > best_match_score:
                                best_match_score = rule_score
                                best_match_count = len(matched_tags)
                                best_fallback_char = char_name
                                best_fallback_tag_details = " | ".join(matched_tags)
                                best_identity_tags = rule_identity_tags
                            elif rule_score == best_match_score and len(matched_tags) > best_match_count:
                                best_match_score = rule_score
                                best_match_count = len(matched_tags)
                                best_fallback_char = char_name
                                best_fallback_tag_details = " | ".join(matched_tags)
                                best_identity_tags = rule_identity_tags
                        else:
                            if current_match_count > 0 and current_match_count >= highest_rejected_score:
                                highest_rejected_score = current_match_count
                                pass_best_rejected_reason = f"Failed to match {char_name}: Only found {current_match_count}/{required_matches} tags"
                    
                    if best_fallback_char:
                        result["best_char"] = best_fallback_char
                        id_tags_str = ", ".join(best_identity_tags)
                        result["reason"] = f"fallback success ({pass_name}: {best_match_score:.3f}, {best_match_count} tags) (Identity - {id_tags_str}) -> [{best_fallback_tag_details}]"
                        return result
                        
                    if highest_rejected_score > highest_rejected_score_overall:
                        highest_rejected_score_overall = highest_rejected_score
                        global_best_rejected_reason = pass_best_rejected_reason

                if len(char_tags) == 0:
                    result["reason"] = "predicted character not present in tag database and fallback failed"
                elif max_char_score < 0.15: 
                    result["reason"] = f"no character detected -> {global_best_rejected_reason}" if global_best_rejected_reason else "no character detected"
                elif len(result["top_3_chars"]) > 1 and result["top_3_chars"][1][1] > (max_char_score * 0.7):
                    result["reason"] = "multiple characters but none above threshold"
                else:
                    result["reason"] = f"fallback failed -> {global_best_rejected_reason}" if global_best_rejected_reason else "confidence below threshold, missing identity/skin tag, or conflicting dominant traits"
                    
                return result


            images_to_process = []
            video_extensions = ('.mp4', '.webm', '.mkv', '.avi', '.mov', '.m4v')
            
            if str(image_path).lower().endswith(video_extensions):
                import cv2
                cap = cv2.VideoCapture(image_path)
                if not cap.isOpened():
                    raise Exception("OpenCV failed to open video file.")
                    
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                if total_frames > 0:
                    scan_points = [
                        (1, int(total_frames * 0.01)),
                        (5, int(total_frames * 0.05)),
                        (10, int(total_frames * 0.10)),
                        (15, int(total_frames * 0.15)),
                        (20, int(total_frames * 0.20)),
                        (30, int(total_frames * 0.30)),
                        (34, int(total_frames * 0.50)),
                        (38, int(total_frames * 0.50)),
                        (45, int(total_frames * 0.50)),
                        (50, int(total_frames * 0.50)),
                        (80, int(total_frames * 0.80)),
                        (90, int(total_frames * 0.90)),
                        (100, total_frames - 1)
                    ]
                    
                    for pct, mark in scan_points:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, mark)
                        ret, frame = cap.read()
                        if ret:
                            msec = cap.get(cv2.CAP_PROP_POS_MSEC)
                            seconds = int(msec / 1000)
                            mins = seconds // 60
                            rem_secs = seconds % 60
                            timestamp_str = f"{mins}:{rem_secs:02d}"
                            
                            frame_label = f"[Frame @ {pct}% | {timestamp_str}]"
                            
                            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            images_to_process.append((Image.fromarray(frame_rgb), frame_label))
                cap.release()
                
                if not images_to_process:
                    raise Exception("OpenCV failed to extract any frames.")
            else:
                image = Image.open(image_path)
                if getattr(image, "is_animated", False):
                    image.seek(image.n_frames // 2)
                    images_to_process.append((image.convert('RGB'), "[GIF Middle Frame]"))
                else:
                    images_to_process.append((image.convert('RGB'), "[Static Image]"))

            best_failure_result = None
            all_failure_reasons = [] 
            
            for idx, (img, frame_label) in enumerate(images_to_process):
                result = evaluate_single_frame(img)
                
                if result and result.get("best_char") is not None:
                    if len(images_to_process) > 1:
                        result["reason"] = f"{frame_label} " + result.get("reason", "")
                    return result
                
                if result:
                    frame_reason = f"{frame_label} {result.get('reason', 'failed')}"
                    all_failure_reasons.append(frame_reason)
                    best_failure_result = result
                
            if best_failure_result and all_failure_reasons:
                best_failure_result["reason"] = " | ".join(all_failure_reasons)
                
            return best_failure_result

        except Exception as e:
            print(f"ONNX Evaluation Error: {e}")
            return None
