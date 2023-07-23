"""
Count duplicate, i.e. overlapping, features of input layer.
"""

import processing
from PyQt5.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterString,
)


# TODO: Refactor
class CountDuplicates(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    ID_FIELD = "ID_FIELD"

    def tr(self, string):
        return QCoreApplication.translate("Processing", string)

    def createInstance(self):
        return CountDuplicates()

    def name(self):
        return "count_duplicates"

    def displayName(self):
        return self.tr("Count duplicates")

    def group(self):
        return self.tr("")

    def groupId(self):
        return ""

    def shortHelpString(self):
        return self.tr("Count Duplicates in input layer.")

    def initAlgorithm(self, config=None):
        # Add the input vector features source
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr("Input layer"),
                [QgsProcessing.TypeVectorAnyGeometry],
            )
        )

        # Add a feature sink in which to store our processed features (this usually takes the form of a
        # newly created vector layer)
        self.addParameter(
            QgsProcessingParameterFeatureSink(self.OUTPUT, self.tr("Output layer"))
        )

    def processAlgorithm(self, parameters, context, feedback):
        # Retrieve the feature source and sink
        source = self.parameterAsSource(parameters, self.INPUT, context)

        if source is None:
            raise QgsProcessingException(
                self.invalidSourceError(parameters, self.INPUT)
            )

        # Create the output layer fields
        out_fields = source.fields()
        out_fields.append(QgsField("COUNT", QVariant.Int, "", 10, 0))

        # Add fields identifying different sketch maps, i.e. the filenames
        name_index = source.fields().indexOf("name")
        values = source.uniqueValues(name_index)

        for id_value in values:
            out_fields.append(QgsField(str(id_value), QVariant.Int, "", 10, 0))

        out_fields.remove(name_index)

        # The 'dest_id' variable is used to uniquely identify the feature sink
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            out_fields,
            source.wkbType(),
            source.sourceCrs(),
        )

        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))


        # Count overlaps for each feature:
        features = source.getFeatures()

        for i, feature in enumerate(features):
            attributes = feature.attributes()
            del attributes[name_index]
            attributes += [0] * (len(out_fields) - len(attributes))  # Initialise new fields with zero

            count = 0  # Each feature 'overlaps' with itself, so the count will be incremented by one in the inner loop

            features_ = source.getFeatures()
            for j, other_feature in enumerate(features_):
                if feature.geometry().equals(other_feature.geometry()):
                    feature_id = other_feature.attributes()[name_index]  # Name of the sketch map this marking is from
                    attributes[out_fields.indexOf(str(feature_id))] = 1  # Set the indicator variable for this
                    #                                                              sketch map to one
                    count += 1
                    if j >= i:  # overlapping feature not already added
                        out_feature = QgsFeature()
                        attributes[out_fields.indexOf("COUNT")] = count
                        out_feature.setAttributes(attributes)
                        out_feature.setGeometry(feature.geometry())
                        sink.addFeature(out_feature, QgsFeatureSink.FastInsert)
        return {self.OUTPUT: dest_id}
