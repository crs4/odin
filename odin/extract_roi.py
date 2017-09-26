try:
    import simplejson as json
except ImportError:
    import json

import os, sys, requests, math
from urlparse import urljoin
from cStringIO import StringIO
from PIL import Image, ImageDraw2


class ROIDataExtractor(object):

    def __init__(self, host, user, passwd, logger):
        self.promort_host = host
        self.ome_seadragon_host = None
        self.user = user
        self.passwd = passwd
        self.logger = logger
        self.promort_client = requests.Session()
        self.ome_seadragon_client = requests.Session()
        self.csrf_token = None
        self.session_id = None

    def _update_payload(self, payload):
        auth_payload = {
            'csrfmiddlewaretoken': self.csrf_token,
            'promort_sessionid': self.session_id
        }
        payload.update(auth_payload)

    def _login(self):
        self.logger.info('Logging as "%s"', self.user)
        url = urljoin(self.promort_host, 'api/auth/login/')
        payload = {'username': self.user, 'password': self.passwd}
        response = self.promort_client.post(url, json=payload)
        if response.status_code == requests.codes.OK:
            self.csrf_token = self.promort_client.cookies.get('csrftoken')
            self.session_id = self.promort_client.cookies.get('promort_sessionid')
            self.logger.info('Successfully logged in')
        else:
            self.logger.critical('Unable to perform login with given credentials')
            sys.exit('Unable to perform login with given credentials')

    def _logout(self):
        payload = {}
        self._update_payload(payload)
        url = urljoin(self.promort_host, 'api/auth/logout/')
        response = self.promort_client.post(url, payload)
        self.logger.info('Logout response code %r', response.status_code)

    def _check_permissions(self):
        self.logger.info('Checking if user has proper permissions')
        url = urljoin(self.promort_host, 'api/odin/check_permissions/')
        response = self.promort_client.get(url)
        if response.status_code == requests.codes.NO_CONTENT:
            return True
        else:
            self.logger.warn('User didn\'t passed permissions check: response code %s', response.status_code)
            return False

    def _load_ome_seadragon_info(self):
        url = urljoin(self.promort_host, 'api/utils/omeseadragon_base_urls/')
        response = self.promort_client.get(url)
        self.ome_seadragon_host = response.json()['base_url']

    def _load_slides_infos(self, case_label):
        url = urljoin(self.promort_host, 'api/cases/%s/' % case_label)
        response = self.promort_client.get(url)
        if response.status_code == requests.codes.OK:
            slides = response.json()['slides']
            return [
                {
                    'id': s['id'],
                    'omero_id': s['omero_id'],
                    'image_type': s['image_type']
                }
                for s in slides if s['image_type']
            ]
        else:
            return []

    def _load_slide_infos(self, slide_label):
        url = urljoin(self.promort_host, 'api/slides/%s/' % slide_label)
        response = self.promort_client.get(url)
        if response.status_code == requests.codes.OK:
            return {
                'omero_id': response.json()['omero_id'],
                'image_type': response.json()['image_type']
            }
        else:
            return None

    def _load_image_details(self, omero_id, is_mirax):
        if is_mirax:
            url = urljoin(self.ome_seadragon_host, 'mirax/deepzoom/get/%s.json' % omero_id)
        else:
            url = urljoin(self.ome_seadragon_host, 'deepzoom/get/%s.json' % omero_id)
        response = self.ome_seadragon_client.get(url)
        if response.status_code == requests.codes.OK:
            return {
                'image_height': int(response.json()['Image']['Size']['Height']),
                'image_width': int(response.json()['Image']['Size']['Width']),
                'tile_size': int(response.json()['Image']['TileSize']),
                'tile_overlap': int(response.json()['Image']['Overlap']),
                'base_url': response.json()['Image']['Url']
            }
        else:
            return None

    def _load_rois_from_http_response(self, response_json):
        rois = []
        for rj in response_json:
            rois.append({
                'slide': rj['slide'],
                'case': rj['case'],
                'reviewer': rj['author'],
                'label': rj['label'],
                'segments': json.loads(rj['roi_json'])['segments']
            })
        return rois

    def _get_rois_by_case(self, case):
        url = urljoin(self.promort_host, 'api/odin/%s/' % case)
        response = self.promort_client.get(url)
        rois = []
        if response.status_code == requests.codes.OK:
            rois = self._load_rois_from_http_response(response.json())
        else:
            self.logger.error(response.status_code)
        return rois

    def _get_rois_by_slide(self, case, slide):
        url = urljoin(self.promort_host, 'api/odin/%s/%s/' % (case, slide))
        response = self.promort_client.get(url)
        rois = []
        if response.status_code == requests.codes.OK:
            rois = self._load_rois_from_http_response(response.json())
        else:
            self.logger.error(response.status_code)
        return rois

    def _get_rois_by_reviewer(self, case, slide, reviewer):
        url = urljoin(self.promort_host, 'api/odin/%s/%s/%s/' % (case, slide, reviewer))
        response = self.promort_client.get(url)
        if response.status_code == requests.codes.OK:
            self.logger.info(len(response.json()))
        else:
            self.logger.error(response.status_code)

    def _get_rois_by_type(self, case, slide, reviewer, roi_type):
        url = urljoin(self.promort_host, 'api/odin/%s/%s/%s/%s/' % (case, slide, reviewer, roi_type))
        response = self.promort_client.get(url)
        if response.status_code == requests.codes.OK:
            self.logger.info(len(response.json()))
        else:
            self.logger.error(response.status_code)

    def _get_roi_by_label(self, case, slide, reviewer, roi_type, roi_label):
        url = urljoin(self.promort_host, 'api/odin/%s/%s/%s/%s/%s/' %
                      (case, slide, reviewer, roi_type, roi_label))
        response = self.promort_client.get(url)
        if response.status_code == requests.codes.OK:
            roi_segments = json.loads(response.json()['roi_json'])['segments']
            return roi_segments
        else:
            return None

    def _get_roi_bounding_box_coordinates(self, roi_segments):
        max_x = max([(seg['point']['x']) for seg in roi_segments])
        min_x = min([(seg['point']['x']) for seg in roi_segments])
        max_y = max([(seg['point']['y']) for seg in roi_segments])
        min_y = min([(seg['point']['y']) for seg in roi_segments])
        return {
            'up_left': (min_x, min_y),
            'up_right': (max_x, min_y),
            'low_right': (max_x, max_y),
            'low_left': (min_x, max_y)
        }


    def _convert_to_tile(self, corner, tile_size):
        return {
            'column': int(corner[0] / tile_size),
            'row': int(corner[1] / tile_size)
        }

    def _get_bbox_tiles(self, roi_bounding_box, tile_size):
        return {
            'up_left': self._convert_to_tile(roi_bounding_box['up_left'], tile_size),
            'up_right': self._convert_to_tile(roi_bounding_box['up_right'], tile_size),
            'low_right': self._convert_to_tile(roi_bounding_box['low_right'], tile_size),
            'low_left': self._convert_to_tile(roi_bounding_box['low_left'], tile_size)
        }

    def _get_max_zoom_level(self, img_height, img_width):
        return int(math.ceil(math.log(max(img_height, img_width), 2))) - 1

    def _get_tile(self, slide_base_url, row, column, tile_size, overlap=0, zoom_level=0, img_format='jpeg'):
        url = urljoin(slide_base_url, '%s/%s_%s.%s' % (zoom_level, column, row, img_format))
        response = self.ome_seadragon_client.get(url, params={'tile_size': tile_size})
        if response.status_code == requests.codes.OK:
            tile = Image.open(StringIO(response.content)).crop((overlap, overlap, tile_size+1, tile_size+1))
        else:
            tile = None
            self.logger.error(url)
        return tile

    def _extract_roi_region(self, roi_bbox, slide_base_url, tile_size, overlap=0, zoom_level=0, img_format='jpeg'):
        region_width = ((roi_bbox['up_right']['column'] - roi_bbox['up_left']['column']) + 1) * tile_size
        region_height = ((roi_bbox['low_left']['row'] - roi_bbox['up_left']['row']) + 1) * tile_size
        region_img = Image.new('RGB', (region_width, region_height))
        for row_index, row in enumerate(xrange(roi_bbox['up_left']['row'], roi_bbox['low_left']['row']+1)):
            for column_index, column in enumerate(xrange(roi_bbox['up_left']['column'],
                                                         roi_bbox['up_right']['column']+1)):
                tile = self._get_tile(slide_base_url, row, column, tile_size, overlap, zoom_level, img_format)
                if tile is None:
                    # retry
                    self.logger.info('Failed loading tile, retry')
                    tile = self._get_tile(slide_base_url, row, column, tile_size, overlap, zoom_level, img_format)
                    if tile is None:
                        raise ValueError('Unable to load tile')
                region_img.paste(tile, (column_index * tile_size, row_index * tile_size))
        return region_img

    def _prepare_output_path(self, output_folder, case_label, slide_label, reviewer):
        output_path = os.path.join(output_folder, case_label, slide_label, reviewer)
        try:
            os.makedirs(output_path)
        except OSError:
            pass
        return output_path

    def _save_region(self, region_img, output_folder, case_label, slide_label, reviewer, roi_label):
        self.logger.info('Saving image')
        output_folder = self._prepare_output_path(output_folder, case_label, slide_label, reviewer)
        file_name = '%s_%s.png' % (slide_label, roi_label)
        out_file = os.path.join(output_folder, file_name)
        with open(out_file, 'w') as of:
            region_img.save(of)
            self.logger.info('Image saved')

    def _extract_roi(self, roi_segments, image_details, tile_size, draw_roi=False):
        if tile_size is not None:
            tile_size = tile_size
        else:
            tile_size = image_details['tile_size']
        bbox_coordinates = self._get_roi_bounding_box_coordinates(roi_segments)
        bbox_tiles = self._get_bbox_tiles(bbox_coordinates, tile_size)
        max_zoom_level = self._get_max_zoom_level(image_details['image_height'], image_details['image_width'])
        translated_roi = self._adapt_roi_to_region(roi_segments, bbox_tiles, tile_size)
        region = self._extract_roi_region(bbox_tiles, image_details['base_url'], tile_size,
                                          image_details['tile_overlap'], max_zoom_level)
        if draw_roi:
            self._draw_roi_on_image(region, translated_roi)
        return region, translated_roi

    def _draw_roi_on_image(self, region_img, roi):
        points = [(segment['point']['x'], segment['point']['y']) for segment in roi]
        # close the line
        points.append(points[0])
        draw = ImageDraw2.Draw(region_img)
        pen = ImageDraw2.Pen(color='black', width=5)
        draw.line(points, pen)

    def _adapt_roi_to_region(self, roi_segments, bbox_tiles, tile_size):
        new_origin_x = bbox_tiles['up_left']['column'] * tile_size
        new_origin_y = bbox_tiles['up_left']['row'] * tile_size
        new_roi_segments = []
        for segment in roi_segments:
            new_roi_segments.append({
                'point': {
                    'x': segment['point']['x'] - new_origin_x,
                    'y': segment['point']['y'] - new_origin_y
                }
            })
        return new_roi_segments

    def _run_C(self, case, out_folder, draw_roi, tile_size):
        slides_infos = self._load_slides_infos(case)
        for info in slides_infos:
            if info['omero_id']:
                self.logger.info(info)
                image_details = self._load_image_details(
                    info['id'] if info['image_type'] == 'MIRAX' else info['omero_id'],
                    info['image_type'] == 'MIRAX'
                )
                self.logger.info(image_details)
                roi_segments_list = self._get_rois_by_case(case)
                for roi in roi_segments_list:
                    self.logger.info('Processing ROI %s of slide %s', roi['label'], roi['slide'])
                    region, translated_roi = self._extract_roi(roi['segments'], image_details, tile_size, draw_roi)
                    self._save_region(region, out_folder, case, roi['slide'], roi['reviewer'], roi['label'])

    def _run_CS(self, case, slide, out_folder, draw_roi, tile_size):
        slide_info = self._load_slide_infos(slide)
        self.logger.info(slide_info)
        if slide_info['omero_id']:
            image_details = self._load_image_details(
                slide if slide_info['image_type'] == 'MIRAX' else slide_info['omero_id'],
                slide_info['image_type'] == 'MIRAX'
            )
            self.logger.info(image_details)
            rois_segments_list = self._get_rois_by_slide(case, slide)
            for roi in rois_segments_list:
                self.logger.info('Processing ROI %s', roi['label'])
                region, translated_roi = self._extract_roi(roi['segments'], image_details, tile_size, draw_roi)
                self._save_region(region, out_folder, case, roi['slide'], roi['reviewer'], roi['label'])

    def _run_CSRTL(self, case, slide, reviewer, roi_type, roi_label, out_folder, draw_roi, tile_size):
        slide_info = self._load_slide_infos(slide)
        if slide_info['omero_id']:
            image_details = self._load_image_details(
                slide if slide_info['image_type'] == 'MIRAX' else slide_info['omero_id'],
                slide_info['image_type'] == 'MIRAX'
            )
            self.logger.info(image_details)
            roi_segments = self._get_roi_by_label(case, slide, reviewer, roi_type, roi_label)
            if roi_segments:
                region, translated_roi = self._extract_roi(roi_segments, image_details, tile_size, draw_roi)
                self._save_region(region, out_folder, case, slide, reviewer, roi_label)
        else:
            self.logger.warn('Slide %s is not linked to an image in OMERO', slide)

    def run(self, case, slide, reviewer, roi_type, roi_label, out_folder, draw_roi, tile_size):
        self._login()
        perm_ok = self._check_permissions()
        if perm_ok:
            self._load_ome_seadragon_info()
            if slide:
                if reviewer:
                    if roi_type:
                        if roi_label:
                            self._run_CSRTL(case, slide, reviewer, roi_type, roi_label, out_folder,
                                            draw_roi, tile_size)
                else:
                    self._run_CS(case, slide, out_folder, draw_roi, tile_size)
            else:
                self._run_C(case, out_folder, draw_roi, tile_size)
        self._logout()


help_doc = """
add doc
"""


def make_parser(parser):
    parser.add_argument('--output-folder', type=str, required=True,
                        help='output folder used to save ROI image and clinical data. It MUST be an existing folder')
    parser.add_argument('--case-id', type=str, required=True, help='case ID')
    parser.add_argument('--slide-id', type=str, help='slide ID')
    parser.add_argument('--reviewer', type=str, help='the user that performed the ROIs annotation')
    parser.add_argument('--roi-type', type=str, choices=['slice', 'core', 'focus_region'],
                        help='the type of the ROI that will be extracted from the slide')
    parser.add_argument('--roi-label', type=str, help='ROI label')
    parser.add_argument('--tile-size', type=int, default=None,
                        help='specify the size of the tiles that will be loaded from the server')
    parser.add_argument('--draw-roi', action='store_true', help='draw the ROI on the output image')


def implementation(host, user, passwd, logger, args):
    rois_extractor = ROIDataExtractor(host, user, passwd, logger)
    rois_extractor.run(args.case_id, args.slide_id, args.reviewer, args.roi_type,
                       args.roi_label, args.output_folder, args.draw_roi, args.tile_size)


def register(registration_list):
    registration_list.append(('extract_rois', help_doc, make_parser, implementation))
